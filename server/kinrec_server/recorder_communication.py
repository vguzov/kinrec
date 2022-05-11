import asyncio
import numpy as np
import json
import time
import logging
import base64
import io
import websockets
import os
from io import BytesIO
from PIL import Image
from collections import namedtuple
from functools import partial
from typing import Optional, Union, List, Sequence
from .internal import RecorderState

logger = logging.getLogger("KRS.recorder_comm")


class RecorderComm:
    class UnmatchedAnswerException(Exception):
        def __init__(self, cmd_report):
            super().__init__()
            self.cmd_report = cmd_report

    class FileReceiveException(Exception):
        pass

    callback_names = [
        "set_kinect_params_reply",
        "get_status_reply",
        "get_kinect_calibration_reply",
        "start_preview_reply",
        "get_preview_frame_reply",
        "stop_preview_reply",
        "start_recording_reply",
        "stop_recording_reply",
        "get_recordings_list_reply",
        "collect_reply",
        "delete_recording_reply",
        "stop_collect_reply",
        "shutdown_reply",
        "reboot_reply",
        "file_receive_start",
        "file_receive_end",
        "file_receive_update"
    ]
    ControllerCallbacks = namedtuple("ControllerCallbacks", " ".join(callback_names))
    unmatched_answers = ["collect_file_start", "collect_file_end"]

    def __init__(self, websocket, controller, recorder_id, connection_close_callback, full_status_update_step=100):
        self._recorder_id = recorder_id
        self._websocket = websocket
        self._kinect_id = None
        self._event_loop_active = False
        self._kinect_calibration = None
        self._recordings_list = None
        self._sent_cmds = []
        self._kinect_status = "kin. not ready"
        self._recorder_transferring = False
        self._recording_paths = {}
        self._current_file_descriptor = None
        self._current_file_size = None
        self._current_file_received = None
        self._current_file_rel_path = None
        self._current_file_rec_id = None
        # self.controller_callbacks: RecorderComm.ControllerCallbacks = None
        self._register_callbacks(controller)
        self._connection_close_callback = connection_close_callback
        self._last_state = RecorderState()
        self._till_full_status_update = 0
        self._full_status_update_step = full_status_update_step
        self._full_status_update_requested = False
        self._last_status_reply_received = True

    def _register_callbacks(self, controller):
        callbacks_list = []
        for callback_name in self.callback_names:
            callback = getattr(controller, "comm_" + callback_name)
            callback = partial(callback, self._recorder_id)
            callbacks_list.append(callback)
        self.controller_callbacks = self.ControllerCallbacks(*callbacks_list)

    def _match_answer(self, cmd_report):
        cmdt = cmd_report["cmd"]
        if cmdt not in self.unmatched_answers:
            for sent_ind, sent_cmdt_event in enumerate(self._sent_cmds):
                sent_cmdt, sent_waiting_event = sent_cmdt_event
                if cmdt == sent_cmdt:
                    self._sent_cmds.remove(sent_cmdt_event)
                    return sent_waiting_event
            raise RecorderComm.UnmatchedAnswerException(cmd_report)
        else:
            return None

    def stop_event_loop(self):
        self._event_loop_active = False

    @property
    def event_loop_active(self) -> bool:
        return self._event_loop_active

    async def event_loop(self):
        self._event_loop_active = True
        while self._event_loop_active:
            await self.process_events()

    async def process_events(self):
        # if self._kinect_id is None:
        #     self._init_kinect_info()
        try:
            msg = await self._websocket.recv()
        except websockets.ConnectionClosed:
            await self.close()
            return
        if isinstance(msg, str):
            msg_text = msg
            msg = json.loads(msg)
            if msg["type"] != "preview_frame":
                logger.debug(f"INCOMING MESSAGE: {msg_text}")
            if 'cmd_report' in msg:
                cmd_report = msg['cmd_report']
                try:
                    waiting_event = self._match_answer(cmd_report)
                except RecorderComm.UnmatchedAnswerException as e:
                    logger.error(f"Received unexpected answer {e.cmd_report}, ignoring...")
                else:
                    cmdt = cmd_report["cmd"]
                    cmd_result = cmd_report["result"]
                    cmd_info = cmd_report["info"]
                    if cmd_result != "OK":
                        logger.error(f"Error on recorder {self._recorder_id}: {cmd_report}")
                        return
                    else:
                        logger.info(f"{cmdt} -- OK")

                    if self._kinect_id is None and cmdt not in ["get_kinect_calibration", "get_status",
                                                                "set_kinect_params"]:
                        logger.error(f"Received {cmdt} before obtaining Kinect info")
                        return

                    if cmdt == "get_status":
                        self._process_status_msg(msg)
                    elif cmdt == "get_kinect_calibration":
                        self._process_calibration_msg(msg)
                    elif cmdt == "set_kinect_params":
                        self.controller_callbacks.set_kinect_params_reply(True)
                    elif cmdt == "start_preview":
                        self.controller_callbacks.start_preview_reply(cmd_result == "OK",
                                                                      info=None if cmd_result == "OK" else cmd_info)
                    elif cmdt == "get_preview_frame":
                        self._process_preview_frame(msg)
                    elif cmdt == "stop_preview":
                        self.controller_callbacks.stop_preview_reply(cmd_result == "OK",
                                                                     info=None if cmd_result == "OK" else cmd_info)
                    elif cmdt == "start_recording":
                        self.controller_callbacks.start_recording_reply(cmd_result == "OK",
                                                                        info=None if cmd_result == "OK" else cmd_info)
                    elif cmdt == "stop_recording":
                        self.controller_callbacks.stop_recording_reply(cmd_result == "OK",
                                                                       info=None if cmd_result == "OK" else cmd_info)
                    elif cmdt == "get_recordings_list":
                        if cmd_result == "OK":
                            self.controller_callbacks.get_recordings_list_reply(True, msg['recordings'])
                        else:
                            self.controller_callbacks.get_recordings_list_reply(False, info=cmd_info)
                    elif cmdt == "collect":
                        self.controller_callbacks.collect_reply(cmd_result == "OK", recording_id=msg['recording_id'],
                                                                files=msg['files'],
                                                                info=None if cmd_result == "OK" else cmd_info)
                    elif cmdt == "delete_recording":
                        self.controller_callbacks.delete_recording_reply(cmd_result == "OK",
                                                                         info=None if cmd_result == "OK" else cmd_info)
                    elif cmdt == "stop_collect":
                        if cmd_result == "OK":
                            self._file_collect_end()
                        self.controller_callbacks.stop_collect_reply(cmd_result == "OK",
                                                                     info=None if cmd_result == "OK" else cmd_info)

                    elif cmdt == "shutdown":
                        self.controller_callbacks.shutdown_reply(cmd_result == "OK",
                                                                 info=None if cmd_result == "OK" else cmd_info)
                    elif cmdt == "reboot":
                        self.controller_callbacks.reboot_reply(cmd_result == "OK",
                                                               info=None if cmd_result == "OK" else cmd_info)
                    if waiting_event is not None:
                        waiting_event.set()
            else:
                if msg["type"] == "collect_file_start":
                    if self._current_file_rec_id is not None:
                        raise self.FileReceiveException(f"Comm {self._recorder_id}:{self._kinect_id}: "
                                                        f"Cannot receive more than one file at once")
                    rec_id = msg["recording_id"]
                    rec_path = self._recording_paths[rec_id]
                    typename, file_ext = os.path.basename(msg["relative_file_path"]).split(".")[-2:]
                    download_folder = ""
                    if "color" in typename:
                        download_folder = "color"
                    elif "depth2pc" in typename:
                        download_folder = "depth2pc_maps"
                    elif "depth" in typename:
                        download_folder = "depth"
                    elif "time" in typename:
                        download_folder = "times"

                    if self.kinect_alias is None:
                        filename = f"_{self.kinect_id}.{file_ext}"
                    else:
                        filename = f"{self.kinect_alias}_{self.kinect_id}.{file_ext}"

                    self._current_file_rel_path = os.path.join(download_folder, filename)
                    self._current_file_rec_id = rec_id
                    file_path = os.path.join(rec_path, self._current_file_rel_path)
                    self._current_file_size = msg["file_size"]
                    self._current_file_received = 0
                    self._current_file_descriptor = open(file_path, "wb")
                    self.controller_callbacks.file_receive_start(self._current_file_rec_id,
                                                                 self._current_file_rel_path,
                                                                 self._current_file_size)

                elif msg["type"] == "collect_file_end":
                    self._file_collect_end()
                else:
                    logger.error(f"Comm {self._recorder_id}:{self._kinect_id}: Unrecognized command '{msg['type']}'")
        else:
            if self._current_file_descriptor is None:
                raise self.FileReceiveException(f"Comm {self._recorder_id}:{self._kinect_id} received a data packet,"
                                                f" but has no opened files to write to")
            else:
                self._current_file_descriptor.write(msg)
                self._current_file_received += len(msg)
                self.controller_callbacks.file_receive_update(self._current_file_rec_id,
                                                              self._current_file_rel_path,
                                                              len(msg),
                                                              self._current_file_received)

    def _file_collect_end(self):
        if self._current_file_descriptor is not None:
            self._current_file_descriptor.close()
        else:
            logger.error(f"Comm {self._recorder_id}:{self._kinect_id}: Received 'collect_file_end', "
                         f"but no file was opened")
        self._current_file_descriptor = None
        if self._current_file_received != self._current_file_size:
            logger.error(f"Comm {self._recorder_id}:{self._kinect_id}: File size mismatch: "
                         f"received {self._current_file_received} but "
                         f"should be {self._current_file_size}")
        self.controller_callbacks.file_receive_end(self._current_file_rec_id,
                                                   self._current_file_rel_path,
                                                   self._current_file_size,
                                                   self._current_file_received)
        self._current_file_received = 0
        self._current_file_size = None
        self._current_file_rec_id = None
        self._current_file_rel_path = None

    async def update_kinect_id(self) -> str:
        event = asyncio.Event()
        await self._send({"type": "get_kinect_calibration"}, event)
        await event.wait()
        return self._kinect_id

    @property
    def kinect_id(self) -> str:
        return self._kinect_id

    @property
    def kinect_alias(self) -> int:
        return self._last_state.kinect_alias

    async def set_kinect_params(self, rgb_res, depth_wfov, depth_binned, fps, sync_mode, sync_capture_delay):
        await self._send({"type": "set_kinect_params", "rgb_res": int(rgb_res), 'depth_wfov': bool(depth_wfov),
                          'depth_binned': bool(depth_binned), 'fps': int(fps), 'sync_mode': sync_mode,
                          'sync_capture_delay': int(sync_capture_delay)})

    async def get_kinect_calibration(self):
        await self._send({"type": "get_kinect_calibration"})

    async def get_status(self, full_update=False):
        if self._till_full_status_update <= 0:
            full_update = True
            self._till_full_status_update = self._full_status_update_step
        else:
            self._till_full_status_update -= 1
        self._full_status_update_requested = self._full_status_update_requested or full_update
        if self._full_status_update_requested:
            optionals = ["disk_space", "battery", "recording_fps"]
            self._till_full_status_update = self._full_status_update_step
        else:
            optionals = []
        if self._last_status_reply_received:
            await self._send({"type": "get_status", "optionals": optionals})
            self._full_status_update_requested = False
            self._last_status_reply_received = False

    async def start_preview(self):
        await self._send({"type": "start_preview"})

    async def get_preview_frame(self, color_scale: Union[float, int] = 1, depth_scale: Optional[int] = 1):
        await self._send({"type": "get_preview_frame", "color_scale": color_scale, "depth_scale": depth_scale})

    async def stop_preview(self):
        await self._send({"type": "stop_preview"})

    async def start_recording(self, recording_id, recording_name, recording_duration, server_time,
            participating_kinects, start_delay):
        await self._send({"type": "start_recording", "recording_id": recording_id, "recording_name": recording_name,
                          "recording_duration": recording_duration, "server_time": server_time,
                          "participating_kinects": participating_kinects, "start_delay": start_delay})

    async def stop_recording(self, server_time):
        await self._send({"type": "stop_recording", "server_time": server_time})

    async def get_recordings_list(self):
        await self._send({"type": "get_recordings_list"})

    async def collect(self, recording_id, recording_path):
        self._recording_paths[recording_id] = recording_path
        await self._send({"type": "collect", "recording_id": recording_id})

    async def delete_recording(self, recording_id):
        await self._send({"type": "delete_recording", "recording_id": recording_id})

    async def stop_collect(self):
        await self._send({"type": "stop_collect"})

    async def shutdown(self):
        await self._send({"type": "shutdown"})

    async def reboot(self):
        await self._send({"type": "reboot"})

    async def _send(self, data, waiting_event=None):
        if isinstance(data, dict):
            logger.info(f"Sending '{data['type']}'")
            self._sent_cmds.append((data['type'], waiting_event))
            data = json.dumps(data)
        try:
            await self._websocket.send(data)
        except websockets.ConnectionClosed:
            await self.close()

    async def close(self):
        self.stop_event_loop()
        await self._websocket.close()
        self.controller_callbacks.get_status_reply(False, self._last_state)
        self._connection_close_callback(self._recorder_id)

    def set_kinect_alias(self, kin_alias: int):
        self._last_state.kinect_alias = kin_alias

    def _init_kinect_info(self):
        self._send({"type": "get_kinect_calibration"})

    def _process_status_msg(self, msg):
        self._kinect_status = msg["kinect_status"]
        self._recorder_transferring = msg["transferring"]
        self._last_state.status = msg["kinect_status"]
        if "battery" in msg["optionals"]:
            if msg["optionals"]["battery"] is None:
                self._last_state.bat_power = 0
                self._last_state.bat_plugged = False
            else:
                self._last_state.bat_power = int(msg["optionals"]["battery"]["percent"])
                self._last_state.bat_plugged = bool(msg["optionals"]["battery"]["plugged"])
        if "disk_space" in msg["optionals"]:
            self._last_state.free_space = int(msg["optionals"]["disk_space"]["free"] / 2 ** 30)
        self._last_status_reply_received = True
        self.controller_callbacks.get_status_reply(True, self._last_state)

    def _process_calibration_msg(self, msg):
        cmd_report = msg['cmd_report']
        cmd_result = cmd_report["result"]
        cmd_info = cmd_report["info"]
        if cmd_result == "OK":
            self._kinect_id = msg["kinect_id"]
            self._last_state.kinect_id = msg["kinect_id"]
            self._kinect_calibration = msg["kinect_calibration"]
            logger.info(f"Got info from Kinect: id {self._kinect_id}")
            self.controller_callbacks.get_kinect_calibration_reply(True, self._kinect_id,
                                                                   self._kinect_calibration)
        else:
            self.controller_callbacks.get_kinect_calibration_reply(False, None, None, info=cmd_info)

    @staticmethod
    def _decode_image(data, format="jpeg"):
        data = base64.b64decode(data.encode("utf-8"))
        img = np.array(Image.open(BytesIO(data), formats=[format]))
        return img

    def _process_preview_frame(self, msg):
        cmd_report = msg['cmd_report']
        cmd_result = cmd_report["result"]
        cmd_info = cmd_report["info"]
        if cmd_result == "OK":
            color_data = msg["color"]
            data = color_data["data"]
            color = self._decode_image(data, "jpeg")
            color_ts = color_data["timestamp"]
            depth_data = msg["depth"]
            if depth_data is not None:
                data = depth_data["data"]
                depth = self._decode_image(data, "png")
                depth_ts = depth_data["timestamp"]
            else:
                depth = None
                depth_ts = None
            self.controller_callbacks.get_preview_frame_reply(True, color, color_ts, depth, depth_ts)
        else:
            self.controller_callbacks.get_preview_frame_reply(False, info=cmd_info)
