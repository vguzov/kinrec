import numpy as np
import kinz
import logging
import time
import io
import os
import json
import shutil
import psutil
import base64
from PIL import Image
from glob import glob
from copy import deepcopy
from skimage.transform import rescale
from threading import Thread
from .net import NetHandler
from videoio import VideoWriter, Uint16Writer
from typing import Tuple, Sequence, List, Optional, IO, Union
from dataclasses import dataclass

logger = logging.getLogger("KR.recorder")

status_possible_results = ["OK", "Kinect fail", "Recorder fail"]
status_possible_results_lower = [x.lower() for x in status_possible_results]


def statusd(cmd, result="OK", info=""):
    assert result.lower() in status_possible_results_lower
    result = status_possible_results[status_possible_results_lower.index(result.lower())]
    return {"cmd": cmd, "result": result, "info": info}


# def se3_inv(R, t):
#     R = R.copy()
#     t = t.copy()
#     R = R.T
#     t = -(R.T).dot(t)
#     return R, t

def se3_inv(mtx):
    mtx = mtx.copy()
    R = mtx[:3, :3].copy()
    t = mtx[:3, 3].copy()
    mtx[:3, :3] = R.T
    mtx[:3, 3] = -(R.T).dot(t)
    return mtx


def make_RT(R, t):
    RT = np.eye(4)
    RT[:3, :3] = R
    RT[:3, 3] = t
    return RT


class Kinect:
    class DoubleActivationException(Exception):
        pass

    class FrameGetFailException(Exception):
        pass

    class NotActivatedException(Exception):
        pass

    _color_resolutions_dict = {
        720: (1280, 720),
        1080: (1920, 1080),
        1440: (2560, 1440),
        1535: (2048, 1536),
        2160: (3840, 2160),
        3072: (4096, 3072)
    }

    _depth_resolutions_dict = {
        # WFOV, binned
        (True, False): (1024, 1024),
        (True, True): (512, 512),
        (False, False): (640, 576),
        (False, True): (320, 288)
    }

    def __init__(self):
        self.device = None
        self.init_frame_timeout = 5.
        self.regular_frame_timeout = 1 / 10.
        self.update_params()
        self.depth_calibration = None
        self.color_calibration = None
        self.depth2pc_map = None
        self._id = None
        self.active = False

    def update_params(self, resolution=1440, wfov=False, binned=False, fps=30, sync_mode="none", sync_capture_delay=0):
        self.params = dict(resolution=resolution, wfov=wfov, binned=binned, fps=fps, sync_mode=sync_mode,
                           sync_capture_delay=sync_capture_delay)
        self._color_resolution = self._color_resolutions_dict[resolution]
        self._depth_resolution = self._depth_resolutions_dict[(wfov, binned)]

    def _start(self, resolution=1440, wfov=False, binned=False, fps=30, sync_mode="none", sync_capture_delay=0):
        if self.active:
            raise Kinect.DoubleActivationException()
        kin = kinz.Kinect(resolution=resolution, wfov=wfov, binned=binned, framerate=fps, sync_mode=sync_mode,
                          sync_capture_delay=sync_capture_delay, imu_sensors=False)
        self.device = kin
        self.active = True
        logger.info("Kinect initialized, getting frame to test")
        try:
            self._get_next_frame(self.init_frame_timeout)
        except Kinect.FrameGetFailException:
            self.device = None
            self.active = False
            self.depth_calibration = None
            self.color_calibration = None
            self.depth2pc_map = None
            kin.close()
            raise

    @property
    def color_resolution(self) -> Tuple[int, int]:
        return self._color_resolution

    @property
    def depth_resolution(self) -> Tuple[int, int]:
        return self._depth_resolution

    @property
    def fps(self) -> float:
        return self.params["fps"]

    def start(self):
        self._start(**self.params)

    @property
    def connected(self) -> bool:
        try:
            self.device.get_serial_number()
        except Exception as e:
            logger.warning(f"KinZ exception: {e}")
            return False
        else:
            return True

    def get_next_frame(self):
        return self._get_next_frame(self.regular_frame_timeout)

    def _get_next_frame(self, timeout: float, retry_period: float = 1 / 40.):
        if not self.active:
            raise Kinect.NotActivatedException()
        stime = time.time()
        while not self.device.get_frames(get_color=True, get_depth=True, get_ir=False, get_sensors=False,
                                         align_depth=False):
            if time.time() - stime > timeout:
                raise Kinect.FrameGetFailException()
            else:
                time.sleep(retry_period)
        color_data = self.device.get_color_data()
        depth_data = self.device.get_depth_data()
        color_ts = int(deepcopy(color_data.timestamp_nsec))
        depth_ts = int(deepcopy(depth_data.timestamp_nsec))
        color = np.array(color_data.buffer, copy=False)[:, :, 2::-1].copy()
        depth = np.array(depth_data.buffer, copy=True)
        return color, depth, color_ts, depth_ts

    def update_calibration(self):
        if not self.active:
            raise Kinect.NotActivatedException()
        if self.color_calibration is None:
            self.depth_calibration = self.device.get_depth_calibration()
            self.color_calibration = self.device.get_color_calibration()
            self.depth2pc_map = self.device.get_depth2pc_map()
            self._id = self.device.get_serial_number()

    def stop(self):
        if not self.active:
            raise Kinect.NotActivatedException()
        self.device.close()
        self.device = None
        self.active = False
        self.depth_calibration = None
        self.color_calibration = None
        self.depth2pc_map = None

    @property
    def calibration_dict(self):
        def intrinsics_to_dict(calib, add_opencv=True):
            resolution = calib.get_size()
            intr_matrix = calib.get_intrinsics_matrix(extended=False)
            calib_dict = {"cx": intr_matrix[0, 2], "cy": intr_matrix[1, 2], "fx": intr_matrix[0, 0],
                          "fy": intr_matrix[1, 1],
                          "width": resolution[0], "height": resolution[1]}
            dist_params = calib.get_distortion_params()
            calib_dict.update(
                {k: dist_params[0, i] for i, k in enumerate(['k1', 'k2', 'p1', 'p2', 'k3', 'k4', 'k5', 'k6'])})
            if add_opencv:
                calib_dict["opencv"] = [calib_dict[x] for x in
                                        ['fx', 'fy', 'cx', 'cy', 'k1', 'k2', 'p1', 'p2', 'k3', 'k4', 'k5', 'k6']]
            return calib_dict

        if self.color_calibration is None:
            return None
        color_calib_dict = intrinsics_to_dict(self.color_calibration)
        depth_calib_dict = intrinsics_to_dict(self.depth_calibration)
        color_R = self.color_calibration.get_rotation_matrix()
        depth_R = self.depth_calibration.get_rotation_matrix()
        color_t = self.color_calibration.get_translation_vector()[:, 0] / 1000.
        depth_t = self.depth_calibration.get_translation_vector()[:, 0] / 1000.
        color_RT = make_RT(color_R, color_t)  # color2world
        depth_RT = make_RT(depth_R, depth_t)  # depth2world
        color_RT_inv = se3_inv(color_RT)  # world2color
        depth_RT_inv = se3_inv(depth_RT)  # world2depth
        color2depth_RT = depth_RT_inv.dot(color_RT)
        depth2color_RT = color_RT_inv.dot(depth_RT)

        return {"color": color_calib_dict,
                "depth": depth_calib_dict,
                "color2depth": {"R": color2depth_RT[:3, :3].tolist(), "t": color2depth_RT[:3, 3].tolist()},
                "depth2color": {"R": depth2color_RT[:3, :3].tolist(), "t": depth2color_RT[:3, 3].tolist()},
                "params": self.params}

    @property
    def id(self) -> str:
        if self._id is None:
            self._id = self.device.get_serial_number()
        return self._id


class RecorderThread(Thread):
    def __init__(self, kinect, recording_dir, expected_timelen=None, fps_window_size=20, final_callback=None,
            start_delay=0):
        super().__init__()
        self.kinect = kinect
        self.recording_dir = recording_dir
        self.expected_timelen = expected_timelen
        self.active = False
        self.fps_window_size = fps_window_size
        self.last_times = np.zeros(self.fps_window_size)
        self.color_timestamps = []
        self.depth_timestamps = []
        self.final_callback = final_callback
        self.exception = None
        self.start_delay = start_delay

    def run(self) -> None:
        with VideoWriter(os.path.join(self.recording_dir, "color.mpeg"), resolution=self.kinect.color_resolution,
                         fps=self.kinect.fps, preset="ultrafast", codec="mpeg2") as color_writer, \
                Uint16Writer(os.path.join(self.recording_dir, "depth.mp4"), resolution=self.kinect.depth_resolution,
                             fps=self.kinect.fps, preset="ultrafast") as depth_writer:
            self.color_timestamps = []
            self.depth_timestamps = []
            self.last_times = np.zeros(self.fps_window_size)
            if self.start_delay > 0:
                logger.info(f"Waiting for {self.start_delay:.2f} seconds before starting")
                time.sleep(self.start_delay)
            stime = time.time()
            self.last_times[-1] = stime
            logger.info("Recording started")
            while self.active:
                try:
                    color, depth, color_ts, depth_ts = self.kinect.get_next_frame()
                except Kinect.FrameGetFailException as e:
                    self.active = False
                    self.exception = e
                else:
                    color_writer.write(color)
                    depth_writer.write(depth)
                    self.color_timestamps.append(color_ts)
                    self.depth_timestamps.append(depth_ts)
                    self.last_times = np.roll(self.last_times, -1)
                    curr_time = time.time()
                    self.last_times[-1] = time.time()
                    if curr_time - stime >= self.expected_timelen:
                        self.active = False
        if self.final_callback is not None:
            self.final_callback()

    @property
    def sliding_window_fps(self):
        return 1 / (self.last_times[1:] - self.last_times[:-1]).mean()

    def start_recording(self):
        self.active = True
        self.start()

    def close_recording(self):
        self.active = False


class MainController:
    class RecordingExistsException(Exception):
        pass

    @dataclass
    class QueuedFile:
        relpath: str
        path: str
        recording_id: int

    def __init__(self, net_handler: NetHandler, recordings_dir="kinrec/recordings"):
        self.net = net_handler
        self.active = False
        self.kinect = Kinect()
        self.recordings_dir = recordings_dir
        os.makedirs(recordings_dir, exist_ok=True)
        self.recording_expected_duration = None
        self.recording_metadata = None
        self.recorder: Optional[RecorderThread] = None
        self.refresh_period = 1 / 100.
        self.current_sendfile: Optional[IO] = None
        self.sendfile_queue = []
        self.sendfile_packet_size = 100_000

    def start_kinect(self):
        self.kinect.start()

    def get_preview_frame(self, color_scale: Union[float, int], depth_scale: Optional[int]):
        def int_scale(img, scale: int):
            if scale != 1:
                img = img[::scale, ::scale]
            return img

        color, depth, color_ts, depth_ts = self.kinect.get_next_frame()
        if isinstance(color_scale, int):
            color = int_scale(color, color_scale)
        else:
            if color.dtype == np.uint8:
                color = (rescale(color.astype(np.float32) / 255., 1. / color_scale,
                                 multichannel=True) * 255.).astype(
                    np.uint8)
            else:
                color = rescale(color, 1. / color_scale, multichannel=True)
        if depth_scale is not None:
            depth = int_scale(depth, depth_scale)
            return color, depth, color_ts, depth_ts
        else:
            return color, None, color_ts, None

    def stop_kinect(self):
        self.kinect.stop()

    @staticmethod
    def get_recording_dirname(recording_id, recording_name):
        return f"{recording_id}_{recording_name}"

    def start_recording(self, recording_id, recording_name, recording_duration, server_time, participating_kinects,
            start_delay=0):
        curr_recording_dir = os.path.join(self.recordings_dir,
                                          self.get_recording_dirname(recording_id, recording_name))
        if os.path.exists(curr_recording_dir):
            raise MainController.RecordingExistsException()
        os.makedirs(curr_recording_dir)
        logger.info("Creating metadata")
        self.start_kinect()
        self.kinect.update_calibration()
        self.recording_metadata = {"id": recording_id, "name": recording_name, "server_time": server_time,
                                   "participating_kinects": list(participating_kinects),
                                   "kinect_id": self.kinect.id, "kinect_calibration": self.kinect.calibration_dict}
        self.recorder = RecorderThread(self.kinect, curr_recording_dir, recording_duration, start_delay=start_delay)
        logger.info("Starting recorder thread")
        self.recorder.start_recording()

    def finalize_recording(self, new_server_time=None):
        logger.info("Finalizing the recording")
        logger.info("Waiting for recorder thread to finish")
        self.recorder.join()
        logger.info("Writting timestamps and metadata")
        timestamps = {"color": self.recorder.color_timestamps, "depth": self.recorder.depth_timestamps}
        json.dump(timestamps, open(os.path.join(self.recorder.recording_dir, "times.json"), "w"), indent=0)
        if new_server_time is None:
            self.recording_metadata["duration"] = self.recorder.expected_timelen
        else:
            self.recording_metadata["duration"] = new_server_time - self.recording_metadata["server_time"]
        self.recording_metadata["actual_duration"] = (max(self.recorder.color_timestamps[-1],
                                                          self.recorder.depth_timestamps[-1]) -
                                                      min(self.recorder.color_timestamps[0],
                                                          self.recorder.depth_timestamps[0]))
        json.dump(self.recording_metadata, open(os.path.join(self.recorder.recording_dir, "metadata.json"), "w"),
                  indent=1)
        np.savez_compressed(os.path.join(self.recorder.recording_dir, "depth2pc_map.npz"),
                            **{self.kinect.id: self.kinect.depth2pc_map})
        logger.info("Stopping Kinect")
        if self.recorder.exception is not None:
            logger.error(f"===Recording stopped with exception {type(self.recorder.exception)}===")
        try:
            self.stop_kinect()
        except Kinect.NotActivatedException:
            logger.error("Tried to stop Kinect, but Kinect is not running")
        else:
            logger.info("Recording finalized successfully")
        self.recorder = None

    def get_recordings(self, with_size=True):
        essential_files = ["metadata.json", "color.mpeg", "depth.mp4", "times.json", "depth2pc_map.npz"]
        recordings_dict = {}
        for dirpath in glob(os.path.join(self.recordings_dir, "*_*")):
            if os.path.isdir(dirpath) and all(os.path.exists(os.path.join(dirpath, x)) for x in essential_files):
                local_metadata = json.load(open(os.path.join(dirpath, "metadata.json")))
                metadata = {k: local_metadata[k] for k in ["id", "name", "duration", "server_time",
                                                           "kinect_id", "participating_kinects",
                                                           "kinect_calibration"]}
                if with_size:
                    size = 0
                    for filename in essential_files[1:]:
                        filepath = os.path.join(dirpath, filename)
                        size += os.path.getsize(filepath)
                    metadata["size"] = size
                recordings_dict[metadata["id"]] = metadata
        return recordings_dict

    def add_recordings_sendfile_queue(self, recording_id: int):
        files_to_transfer = ["color.mpeg", "depth.mp4", "times.json", "depth2pc_map.npz"]
        recordings_dict = self.get_recordings(with_size=False)
        if recording_id not in recordings_dict:
            raise FileNotFoundError()
        recording_name = recordings_dict[recording_id]["name"]
        dirpath = os.path.join(self.recordings_dir, self.get_recording_dirname(recording_id, recording_name))
        for filename in files_to_transfer:
            filepath = os.path.join(dirpath, filename)
            self.sendfile_queue.append(self.QueuedFile(relpath=filename, path=filepath, recording_id=recording_id))
        return files_to_transfer

    def delete_recording(self, recording_id: int):
        logger.info(f"Will delete recording {recording_id}")
        files_to_delete = ["metadata.json", "color.mpeg", "depth.mp4", "times.json", "depth2pc_map.npz"]
        recordings_dict = self.get_recordings(with_size=False)
        if recording_id not in recordings_dict:
            raise FileNotFoundError()
        recording_name = recordings_dict[recording_id]["name"]
        dirpath = os.path.join(self.recordings_dir, self.get_recording_dirname(recording_id, recording_name))
        for filename in files_to_delete:
            filepath = os.path.join(dirpath, filename)
            if os.path.isfile(filepath):
                os.remove(filepath)
        if len(os.listdir(dirpath)) == 0:
            os.rmdir(dirpath)

    def handle_recording(self):
        if self.recorder is not None:
            if not self.recorder.active:
                self.finalize_recording()
                self.net.send({"type": "pong", "cmd_report": statusd("stop_recording")})

    def handle_sendfile(self):
        if self.current_sendfile is not None:
            data = self.current_sendfile.read(self.sendfile_packet_size)
            if len(data) == 0:
                current_file_info = self.sendfile_queue[0]
                self.net.send({"type": "collect_file_end", "recording_id": current_file_info.recording_id,
                               "relative_file_path": current_file_info.relpath})
                self.sendfile_queue = self.sendfile_queue[1:]
                self.current_sendfile.close()
                self.current_sendfile = None
            else:
                self.net.send(data)
        elif len(self.sendfile_queue) > 0:
            current_file_info = self.sendfile_queue[0]
            size = os.path.getsize(current_file_info.path)
            self.net.send({"type": "collect_file_start", "recording_id": current_file_info.recording_id,
                           "relative_file_path": current_file_info.relpath, "file_size": size})
            self.current_sendfile = open(current_file_info.path, "rb")

    def image_encode(self, image: np.ndarray, format: str = "jpeg"):
        fp = io.BytesIO()
        Image.fromarray(image).save(fp, format)
        img_encoded = fp.getvalue()
        b64encoded = base64.b64encode(img_encoded).decode("utf-8")
        return b64encoded

    def main_loop(self):
        self.active = True
        while self.active:
            if not self.net.active:
                self.active = False
                break
            msg = self.net.get(wait=False)
            self.handle_recording()
            self.handle_sendfile()
            if msg is None:
                time.sleep(self.refresh_period)
                continue
            msgt = msg["type"]
            logger.info(f"[MESSAGE] {msgt}")
            if msgt == "start_preview":
                try:
                    self.start_kinect()
                except Kinect.FrameGetFailException:
                    self.net.send({"type": "pong", "cmd_report":
                        statusd(msgt, "kinect fail", f"Failed to acquire a readable frame within "
                                                     f"{self.kinect.init_frame_timeout} seconds")})
                except Kinect.DoubleActivationException:
                    self.net.send({"type": "pong", "cmd_report":
                        statusd(msgt, "recorder fail", f"Kinect is already activated")})
                else:
                    self.net.send({"type": "pong", "cmd_report": statusd(msgt)})
            elif msgt == "get_preview_frame":
                color_scale = msg["color_scale"]
                depth_scale = msg["depth_scale"]
                try:
                    color, depth, color_ts, depth_ts = self.get_preview_frame(color_scale, depth_scale)
                except Kinect.NotActivatedException:
                    self.net.send({"type": "preview_frame", "cmd_report":
                        statusd(msgt, "kinect fail", f"Kinect is not activated")})
                except Kinect.FrameGetFailException:
                    self.net.send({"type": "preview_frame", "cmd_report":
                        statusd(msgt, "kinect fail", f"Failed to acquire a readable frame within "
                                                     f"{self.kinect.regular_frame_timeout} seconds")})
                else:
                    color_data = {"timestamp": color_ts, "data": self.image_encode(color, "jpeg")}
                    depth_data = None
                    if depth_scale is not None:
                        depth_data = {"timestamp": depth_ts, "data": self.image_encode(depth, "png")}
                    self.net.send({"type": "preview_frame", "cmd_report":
                        statusd(msgt), "color": color_data, "depth": depth_data})
            elif msgt == "stop_preview":
                try:
                    self.stop_kinect()
                except Kinect.NotActivatedException:
                    self.net.send({"type": "preview_frame", "cmd_report":
                        statusd(msgt, "kinect fail", f"Kinect is not activated")})
                else:
                    self.net.send({"type": "pong", "cmd_report": statusd(msgt)})
            elif msgt == "start_recording":
                try:
                    self.start_recording(msg["recording_id"], msg["recording_name"], msg["recording_duration"],
                                         msg["server_time"], msg["participating_kinects"], msg["start_delay"])
                except MainController.RecordingExistsException:
                    self.net.send({"type": "pong", "cmd_report": statusd(msgt, "recorder fail",
                                                                         "Recording already exists")})
                except Kinect.DoubleActivationException:
                    self.net.send({"type": "pong", "cmd_report":
                        statusd(msgt, "recorder fail", f"Kinect is already activated")})
                except Kinect.FrameGetFailException:
                    self.net.send({"type": "pong", "cmd_report":
                        statusd(msgt, "kinect fail", f"Failed to acquire a readable frame within "
                                                     f"{self.kinect.init_frame_timeout} seconds")})
                else:
                    self.net.send({"type": "pong", "cmd_report": statusd(msgt)})
            elif msgt == "stop_recording":
                if self.recorder is None:
                    self.net.send({"type": "pong", "cmd_report": statusd(msgt, "recorder fail",
                                                                         "No recording is running")})
                else:
                    self.recorder.active = False
                    self.finalize_recording(msg["server_time"])
                    self.net.send({"type": "pong", "cmd_report": statusd(msgt)})
            elif msgt == "get_recordings_list":
                rec_dict = self.get_recordings()
                self.net.send({"type": "recordings_list", "cmd_report": statusd(msgt), "recordings": rec_dict})
            elif msgt == "collect":
                recording_id = msg["recording_id"]
                try:
                    added_files = self.add_recordings_sendfile_queue(recording_id)
                except FileNotFoundError:
                    self.net.send({"type": "pong", "cmd_report": statusd(msgt, "recorder fail",
                                                                         f"Recording {msg['recording_id']} does not exist"),
                                   "recording_id": recording_id, "files": None})
                else:
                    self.net.send({"type": "pong", "cmd_report": statusd(msgt, info=f"Will transfer"
                                                                                    f" {len(added_files)} files"),
                                   "recording_id": recording_id, "files": added_files})
            elif msgt == "stop_collect":
                if self.current_sendfile is not None:
                    self.current_sendfile.close()
                    self.current_sendfile = None
                self.sendfile_queue = []
                self.net.send({"type": "pong", "cmd_report": statusd(msgt)})
            elif msgt == "delete_recording":
                try:
                    self.delete_recording(msg["recording_id"])
                except FileNotFoundError:
                    self.net.send({"type": "pong", "cmd_report": statusd(msgt, "recorder fail",
                                                                         f"Recording {msg['recording_id']} does not exist")})
                else:
                    self.net.send({"type": "pong", "cmd_report": statusd(msgt)})
            elif msgt == "get_kinect_calibration":
                was_active = self.kinect.active
                try:
                    if not was_active:
                        self.kinect.start()
                    self.kinect.update_calibration()
                    calibration_dict = self.kinect.calibration_dict
                    if not was_active:
                        self.kinect.stop()
                except Kinect.FrameGetFailException:
                    self.net.send({"type": "kinect_calibration", "cmd_report": statusd(msgt, "kinect fail",
                                                                                       "Failed to activate Kinect")})
                else:
                    self.net.send({"type": "kinect_calibration", "cmd_report": statusd(msgt),
                                   "kinect_calibration": calibration_dict, "kinect_id": self.kinect.id})
            elif msgt == "set_kinect_params":
                self.kinect.update_params(msg["rgb_res"], msg["depth_wfov"], msg["depth_binned"],
                                          msg["fps"], msg["sync_mode"], msg["sync_capture_delay"])
                self.net.send({"type": "pong", "cmd_report": statusd(msgt)})
            elif msgt == "get_status":
                info = ""
                recording_fps = 0
                optionals = {}
                # Kinect statuses (new: "ready", "preview", "recording", "kin. not ready",
                #                  old: "recording", "active", "idle", "disconnected")
                if self.kinect.active:
                    if self.recorder is not None:
                        kin_state = "recording"
                        recording_fps = self.recorder.sliding_window_fps
                        info = f"Recording at {recording_fps:.2f} FPS"
                    else:
                        kin_state = "preview"
                else:
                    if self.kinect.connected:
                        kin_state = "ready"
                    else:
                        kin_state = "kin. not ready"
                if "optionals" in msg:
                    for opt_name in msg["optionals"]:
                        if opt_name == "recording_fps":
                            optionals["recording_fps"] = recording_fps
                        elif opt_name == "disk_space":
                            total, used, free = shutil.disk_usage(self.recordings_dir)
                            optionals["disk_space"] = {"total": total, "used": used, "free": free}
                        elif opt_name == "battery":
                            battery = psutil.sensors_battery()
                            if battery is None:
                                optionals["battery"] = None
                            else:
                                plugged = battery.power_plugged
                                percent = battery.percent
                                optionals["battery"] = {"percent": percent, "plugged": plugged}
                self.net.send({"type": "status", "cmd_report": statusd(msgt),
                               "kinect_status": kin_state, "info": info,
                               "transferring": len(self.sendfile_queue) > 0,
                               "optionals": optionals})
            elif msgt == "shutdown":
                self.net.send({"type": "pong", "cmd_report": statusd(msgt)})
                logger.info("Received shutdown message, attempting to call 'sudo shutdown -s now'")
                os.system("sudo shutdown now")
            elif msgt == "reboot":
                self.net.send({"type": "pong", "cmd_report": statusd(msgt)})
                logger.info("Received reboot message, attempting to call 'sudo shutdown -r now'")
                os.system("sudo shutdown -r now")
            else:
                logger.warning(f"Unrecognized command '{msgt}'")
                self.net.send(
                    {"type": "pong", "cmd_report": statusd(msgt, "recorder fail", "Unrecognized command")})
        logger.info("Main controller loop completed")
