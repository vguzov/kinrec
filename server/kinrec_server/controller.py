import asyncio

import numpy as np
import logging
import os
import time
import json
import websockets
# import cv2
import matplotlib.cm
from skimage.io import imsave
from PIL import Image
from collections import defaultdict
from .recorder_communication import RecorderComm
from typing import Dict, Optional, Union, Sequence, Mapping, List
from .internal import RecorderState, KinectParams, KinectNotReadyException, RecorderDisconnectedException, RecordsEntry, \
    KinectCalibration
from .view import KinRecView

logger = logging.getLogger("KRS.controller")


class KinRecController:
    def __init__(self, kinect_alias_mapping: Dict[Optional[str], Optional[int]] = None, preview_fps=10.,
            workdir='./kinrec'):
        if kinect_alias_mapping is None:
            kinect_alias_mapping = defaultdict(lambda: None)
        self._workdir = workdir
        self._kinect_id_mapping: Dict[Optional[str], Optional[int]] = kinect_alias_mapping
        self._view: Optional[KinRecView] = None
        self._connected_recorders: Dict[int, RecorderComm] = {}
        self._preview_loop_active = defaultdict(lambda: False)
        self._preview_fps = preview_fps
        self._preview_frame_received = asyncio.Event()
        self._preview_frame_received.set()
        self._depth_cm = matplotlib.cm.get_cmap('jet')
        self._depth_preview_thresh = 5000.
        self._last_kinect_params = KinectParams()
        self._params_applied_responses = {}
        self._recordings_database: Dict[int, RecordsEntry] = {}
        self._recorder_reclist_responses = {}
        self._sync_capture_delay = 160  # in nanoseconds
        self._master_recorder = None
        self._curr_recording_participating_kinects = None
        self._curr_recording_started_ids: Optional[set] = None
        self._curr_recording_stopped_ids: Optional[set] = None
        self._curr_state = "idle"
        self._files_to_collect: Dict[int, List[str]] = defaultdict(list)
        self._recordings_received_size: Dict[int, int] = {}
        self._receive_speed_timeframe = 3
        self._recordings_received_last_size: Dict[int, np.ndarray] = {}
        self._recordings_received_last_timestamp: Dict[int, int] = {}

    def kinect_alias_from_recorder(self, recorder_id: int) -> Optional[int]:
        return self._kinect_id_mapping[self._connected_recorders[recorder_id].kinect_id]

    def kinect_alias_from_kinect(self, kinect_id: str) -> Optional[int]:
        return self._kinect_id_mapping[kinect_id]

    async def _start_preview(self, recorder_id, color_scale: Union[float, int] = 3,
            depth_scale: Optional[int] = 1):
        self._preview_loop_active[recorder_id] = True
        recorder = self._connected_recorders[recorder_id]
        await recorder.start_preview()
        while self._preview_loop_active[recorder_id]:
            await self._preview_frame_received.wait()
            if self._preview_loop_active[recorder_id]:
                await recorder.get_preview_frame(color_scale, depth_scale)
                self._preview_frame_received.clear()
                await asyncio.sleep(1. / self._preview_fps)

    async def _stop_preview(self, recorder_id: int):
        self._preview_loop_active[recorder_id] = False
        recorder = self._connected_recorders[recorder_id]
        await recorder.stop_preview()
        self._preview_frame_received.set()

    def _sort_recorders(self):
        recorder_ids = list(self._connected_recorders.keys())
        recorder_aliases = [self.kinect_alias_from_recorder(recorder_id) for recorder_id in recorder_ids]
        if any(alias is None for alias in recorder_aliases):
            logger.error("Cannot sort Recorders: some ids/aliases are not known")
            return None
        else:
            recorder_aliases_sort_order = np.argsort(recorder_aliases)
            recorder_ids = np.array(recorder_ids)[recorder_aliases_sort_order]
            return recorder_ids

    async def _apply_last_kinect_params(self, ignore_sync=True):
        kinect_params = self._last_kinect_params
        will_sync = kinect_params.sync and not ignore_sync
        if will_sync:
            recorder_ids = self._sort_recorders()
            if recorder_ids is None:
                return None
            master_recorder = recorder_ids[0]
            recorder_sync_delays = self._sync_capture_delay * np.arange(len(recorder_ids))
            recorder_sync_delays = {kin_id: delay for kin_id, delay in zip(recorder_ids, recorder_sync_delays)}
        routines = []
        if len(self._connected_recorders) > 0:
            for recorder_id, recorder in self._connected_recorders.items():
                sync_mode = "none"
                if will_sync:
                    recorder_sync_delay = recorder_sync_delays[recorder_id]
                    if recorder_id == master_recorder:
                        sync_mode = "master"
                    else:
                        sync_mode = "subordinate"
                else:
                    recorder_sync_delay = 0
                self._params_applied_responses[recorder_id] = None
                routines.append(recorder.set_kinect_params(kinect_params.rgb_res, kinect_params.depth_wfov,
                                                           kinect_params.depth_binned,
                                                           kinect_params.fps, sync_mode, recorder_sync_delay))
            await asyncio.gather(*routines)
            return master_recorder if will_sync else None
        else:
            return None

    async def _start_recording(self, recording_name: str, recording_duration: float, start_delay: float):
        participating_recorders = self._sort_recorders()
        if participating_recorders is None:
            participating_recorders = list(self._connected_recorders.keys())
        participating_kinects = [self._connected_recorders[rid].kinect_id for rid in participating_recorders]
        if any(x is None for x in participating_kinects):
            raise KinectNotReadyException("Could not get a kinect id from one of the recorders")
        self._curr_recording_participating_kinects = set(participating_recorders)
        master_recorder_id = await self._apply_last_kinect_params(ignore_sync=False)
        server_time = time.time()
        recording_id = int(server_time * 1000)  # recording_id is a start time in ms
        routines = []
        for recorder_id, recorder in self._connected_recorders.items():
            delay = 0
            if master_recorder_id is None or recorder_id == master_recorder_id:
                delay = start_delay
            routines.append(recorder.start_recording(recording_id, recording_name, recording_duration, server_time,
                                                     participating_kinects, delay))
        await asyncio.gather(*routines)

    def _clear_from_last_recording(self):
        self._curr_recording_participating_kinects = None
        self._master_recorder = None
        self._curr_recording_started_ids = None
        self._curr_recording_stopped_ids = None

    def _compile_recordings_list(self, recorderwise_reclists: Dict[int, dict]):
        recordings_completeness_tracker = {}
        self._recordings_database = {}
        self._recorderwise_reclists = {}
        for recorder_id, recordings_dict in recorderwise_reclists.items():
            self._recorderwise_reclists[recorder_id] = {}
            for recording_id, recording_info in recordings_dict.items():
                recording_id = int(recording_id)
                self._recorderwise_reclists[recorder_id][recording_id] = recording_info
                if recording_id not in self._recordings_database:
                    recording = RecordsEntry.from_dict(recording_info)
                    recordings_completeness_tracker[recording_id] = recording_info["participating_kinects"]
                    self._recordings_database[recording_id] = recording
                else:
                    recording = self._recordings_database[recording_id]
                    recording.size += recording_info["size"]
                kinect_id = recording_info["kinect_id"]
                if kinect_id not in recordings_completeness_tracker[recording_id]:
                    logger.error("Kinect ID is not in the participating kinects")
                else:
                    if recording.params.sync and recording_info["kinect_calibration"]["params"][
                        "sync_mode"] == "master":
                        recording.params.sync_master_id = kinect_id
                    recordings_completeness_tracker[recording_id].remove(kinect_id)
                    recording.participating_kinects[kinect_id] = \
                        KinectCalibration.from_dict(recording_info["kinect_calibration"])
        for recording_id, recording in self._recordings_database.items():
            if len(recordings_completeness_tracker[recording_id]) == 0:
                recording.status = "Consistent"
            else:
                recording.status = "Inconsistent (missing " + ", ".join(
                    recordings_completeness_tracker[recording_id]) + ")"
        logger.info(f"Compiled a recording database with {len(self._recordings_database)} entries")
        self._view.browse_recordings_reply(self._recordings_database)

    @staticmethod
    def get_recording_dirname(recording_id, recording_name):
        return f"{recording_id}_{recording_name}"

    async def _collect_recordings(self, recordings_to_collect):
        routines = []
        rec_folders = ["color", "depth", "times", "depth2pc_maps"]
        for rec_id in recordings_to_collect:
            logger.info(f"Collecting recording {rec_id}")
            recording = self._recordings_database[rec_id]
            self._recordings_received_size[rec_id] = 0
            self._recordings_received_last_size[rec_id] = np.zeros(self._receive_speed_timeframe, dtype=np.int64)
            self._recordings_received_last_timestamp[rec_id] = 0
            participating_kinects = set(recording.participating_kinects.keys())
            curr_routines = []
            ready_kinects = set()
            rec_path = os.path.join(self._workdir, "recordings", self.get_recording_dirname(rec_id, recording.name))
            for rec_folder in rec_folders:
                os.makedirs(os.path.join(rec_path, rec_folder), exist_ok=True)
            recording_dict = recording.to_dict()
            self._curr_collection_participating_recorders = []
            for recorder_id, recorder in self._connected_recorders.items():
                if rec_id in self._recorderwise_reclists[recorder_id]:
                    recorder_recording_kinect_id = self._recorderwise_reclists[recorder_id][rec_id]["kinect_id"]
                    if recorder_recording_kinect_id in participating_kinects:
                        kin_alias = self.kinect_alias_from_kinect(recorder_recording_kinect_id)
                        recording_dict["participating_kinects"][recorder_recording_kinect_id]["alias"] = kin_alias
                        if kin_alias is None:
                            file_prefix = f"_{recorder_recording_kinect_id}"
                        else:
                            file_prefix = f"{kin_alias}_{recorder_recording_kinect_id}"
                        curr_routines.append(recorder.collect(rec_id, rec_path, file_prefix))
                        ready_kinects.add(recorder_recording_kinect_id)
                else:
                    logger.warning(f"{rec_id} not in {list(self._recorderwise_reclists[recorder_id].keys())}")
            json.dump(recording_dict, open(os.path.join(rec_path, "metadata.json"), "w"), indent=2)
            if ready_kinects == participating_kinects:
                routines += curr_routines
            else:
                logger.error(
                    f"Recording {rec_id} cannot be collected: the following kinects are missing {participating_kinects - ready_kinects}")
        await asyncio.gather(*routines)

    async def _delete_recordings(self, recordings_to_delete):
        for rec_id in recordings_to_delete:
            curr_routines = []
            logger.info(f"Deleting recording {rec_id} from kinects")
            recording = self._recordings_database[rec_id]
            participating_kinects = set(recording.participating_kinects)
            for recorder_id, recorder in self._connected_recorders.items():
                if recorder.kinect_id in participating_kinects:
                    curr_routines.append(recorder.delete_recording(rec_id))
            await asyncio.gather(*curr_routines)

    ### Actions ###
    def start_preview(self, recorder_id: int) -> bool:
        if recorder_id not in self._connected_recorders:
            logger.warning(f"A preview for recorder {recorder_id} was asked, but not such recorder exists")
            return False
        self._curr_state = "preview"
        asyncio.create_task(self._start_preview(recorder_id))
        return True

    def stop_preview(self, recorder_id: int) -> bool:
        if recorder_id not in self._connected_recorders:
            logger.warning(f"A 'stop preview' for recorder {recorder_id} was asked, but not such recorder exists")
            return False
        self._curr_state = "idle"
        asyncio.create_task(self._stop_preview(recorder_id))
        return True

    def start_recording(self, recording_name: str, recording_duration: float = None, start_delay: float = 10.):
        self._curr_recording_started_ids = set()
        self._curr_state = "recording"
        asyncio.create_task(self._start_recording(recording_name, recording_duration, start_delay))

    def stop_recording(self):
        self._curr_recording_stopped_ids = set()
        server_time = time.time()
        for recorder_id in self._curr_recording_participating_kinects:
            if recorder_id not in self._connected_recorders:
                logger.error(f"Failed to stop the recording: {recorder_id} disconnected")
                # raise RecorderDisconnectedException(f"Failed to stop the recording: {recorder_id} disconnected")
        self._curr_state = "idle"
        for recorder_id in self._curr_recording_participating_kinects:
            recorder = self._connected_recorders[recorder_id]
            asyncio.create_task(recorder.stop_recording(server_time))

    def apply_kinect_params(self, kinect_params: KinectParams):
        self._last_kinect_params = kinect_params
        asyncio.create_task(self._apply_last_kinect_params())

    def collect_recordings(self, recording_ids: Sequence[int]):
        asyncio.create_task(self._collect_recordings(recording_ids))

    def delete_recordings(self, recording_ids: Sequence[int]):
        asyncio.create_task(self._delete_recordings(recording_ids))

    def collect_recordings_info(self):
        self._recordings_database = {}
        self._recorder_reclist_responses = {}
        for recorder_id, recorder in self._connected_recorders.items():
            self._recorder_reclist_responses[recorder_id] = None
            asyncio.create_task(recorder.get_recordings_list())

    def shutdown(self):
        for recorder_id, recorder in self._connected_recorders.items():
            asyncio.create_task(recorder.shutdown())

    def reboot(self):
        for recorder_id, recorder in self._connected_recorders.items():
            asyncio.create_task(recorder.reboot())

    ### Methods ###
    def set_view(self, view: KinRecView):
        self._view = view
        self._view.update_server_state("online")
        self._view.kinect_params_init(self._last_kinect_params)

    async def add_recorder(self, recorder: RecorderComm, recorder_id: int):
        assert recorder_id not in self._connected_recorders
        self._connected_recorders[recorder_id] = recorder
        await recorder.get_kinect_calibration()
        current_params = self._last_kinect_params
        await recorder.set_kinect_params(current_params.rgb_res, current_params.depth_wfov,
                                         current_params.depth_binned, current_params.fps, "none", 0)

    def remove_recorder(self, recorder_id):
        del self._connected_recorders[recorder_id]

    async def ask_kinect_status(self):
        status_routines = [comm.get_status() for comm in self._connected_recorders.values()]
        await asyncio.gather(*status_routines)

    ### Callbacks ###
    def comm_get_status_reply(self, recorder_id: int, reply_result: bool, recorder_state: RecorderState):
        if reply_result:
            self._view.update_recorder_state(recorder_id, recorder_state)
        else:
            self._view.update_recorder_state(recorder_id, RecorderState())

    def comm_get_kinect_calibration_reply(self, recorder_id: int, reply_result: bool,
            kinect_id: str, kinect_calibration: dict, info: str = None):
        kin_alias = self.kinect_alias_from_recorder(recorder_id)
        self._connected_recorders[recorder_id].set_kinect_alias(kin_alias)
        if not reply_result:
            logger.warning(f"Recorder {recorder_id}:{kin_alias} Failed to obtain kinect calibration, more info: {info}")

    def comm_set_kinect_params_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        self._params_applied_responses[recorder_id] = reply_result
        if not reply_result:
            kin_alias = self.kinect_alias_from_recorder(recorder_id)
            logger.warning(f"Recorder {recorder_id}:{kin_alias} Failed to set parameters, more info: {info}")
        responses = list(self._params_applied_responses.values())
        done_responses = [x is not None for x in responses]
        if all(done_responses):
            self._view.params_apply_finalize(all(responses))

    def comm_start_preview_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        if reply_result:
            self._view.start_preview(recorder_id)
        else:
            kin_alias = self.kinect_alias_from_recorder(recorder_id)
            logger.warning(f"Recorder {recorder_id}:{kin_alias} Preview failed to start, more info: {info}")

    def comm_get_preview_frame_reply(self, recorder_id: int, reply_result: bool, color: np.ndarray, color_ts: int,
            depth: Optional[np.ndarray], depth_ts: Optional[int], info: str = None):
        target_res = self._view.preview_frame_size
        color_res = np.array(color.shape[:2][::-1])
        if depth is not None:
            depth_res = np.array(depth.shape[:2][::-1])
            depth_scale = color_res[1] / depth_res[1]
            curr_res = (color_res[0] + depth_res[0] * depth_scale, color_res[1])
            depth_img = self._depth_cm(depth.astype(float) / self._depth_preview_thresh)
            depth_img = (depth_img[:, :, :3] * 255.).astype(np.uint8)
        else:
            curr_res = color_res
        target_scale = min(target_res[0] / curr_res[0], target_res[1] / curr_res[1])
        color_res = (color_res * target_scale).astype(int)
        color_res[1] = min(color_res[1], target_res[1])
        color_pil = Image.fromarray(color)
        color_resized = np.array(color_pil.resize(color_res, Image.NEAREST))
        if depth is not None:
            depth_scale = depth_scale * target_scale
            depth_res = (depth_res * depth_scale).astype(int)
            depth_res[1] = color_res[1]
            depth_pil = Image.fromarray(depth_img)
            depth_resized = np.array(depth_pil.resize(depth_res, Image.NEAREST))
            target_img = np.hstack([color_resized, depth_resized])
        else:
            target_img = color_resized
        logger.info(f"Made a preview frame with resolution {target_img.shape}")
        self._preview_frame_received.set()
        self._view.set_preview_frame(target_img)

    def comm_stop_preview_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        self._view.stop_preview(recorder_id)
        if not reply_result:
            kin_alias = self.kinect_alias_from_recorder(recorder_id)
            logger.warning(f"Recorder {recorder_id}:{kin_alias} Preview failed to stop, more info: {info}")

    def comm_start_recording_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        if reply_result:
            self._curr_recording_started_ids.add(recorder_id)
        else:
            kin_alias = self.kinect_alias_from_recorder(recorder_id)
            logger.warning(f"Recorder {recorder_id}:{kin_alias} Recording failed to start, more info: {info}")
            self.stop_recording()
            self._view.start_recording_reply(False)
        if self._curr_recording_started_ids == self._curr_recording_participating_kinects:
            self._view.start_recording_reply(True)
            self._curr_recording_stopped_ids = set()

    def comm_stop_recording_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        if reply_result:
            self._curr_recording_stopped_ids.add(recorder_id)
        else:
            kin_alias = self.kinect_alias_from_recorder(recorder_id)
            logger.warning(f"Recorder {recorder_id}:{kin_alias} Recording failed to stop, more info: {info}")
            self._curr_recording_stopped_ids.add(recorder_id)
        if self._curr_recording_stopped_ids == self._curr_recording_participating_kinects:
            self._view.stop_recording_reply()
            self._clear_from_last_recording()

    def comm_get_recordings_list_reply(self, recorder_id: int, reply_result: bool, recordings: Dict[int, dict] = None,
            info: str = None):
        if reply_result:
            self._recorder_reclist_responses[recorder_id] = recordings
        else:
            self._recorder_reclist_responses[recorder_id] = {}
            kin_alias = self.kinect_alias_from_recorder(recorder_id)
            logger.error(
                f"Recorder {recorder_id}:{kin_alias} failed to acquire recordings, more info: {info}")
        replies = list(self._recorder_reclist_responses.values())
        completed_replies = [x is not None for x in replies]
        if all(completed_replies):
            self._compile_recordings_list(self._recorder_reclist_responses)

    def comm_collect_reply(self, recorder_id: int, reply_result: bool, recording_id: int, files: List[str],
            info: str = None):
        if not reply_result:
            kin_alias = self.kinect_alias_from_recorder(recorder_id)
            logger.error(
                f"Recorder {recorder_id}:{kin_alias} failed to acquire recording {recording_id}, more info: {info}")
        else:
            self._files_to_collect[recorder_id] += files
            logger.info(f"Will collect {len(files)} for recording {recording_id}")

    def comm_delete_recording_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_stop_collect_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_shutdown_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        kin_alias = self.kinect_alias_from_recorder(recorder_id)
        if reply_result:
            logger.warning(f"Recorder {recorder_id}:{kin_alias} shutdown")
        else:
            logger.error(f"Recorder {recorder_id}:{kin_alias} failed to shut down, more info: {info}")

    def comm_reboot_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        kin_alias = self.kinect_alias_from_recorder(recorder_id)
        if reply_result:
            logger.warning(f"Recorder {recorder_id}:{kin_alias} reboot")
        else:
            logger.error(f"Recorder {recorder_id}:{kin_alias} failed to reboot, more info: {info}")

    def comm_file_receive_start(self, recorder_id: int, file_rec_id: int, file_rel_path: str, file_size: int):
        kin_alias = self.kinect_alias_from_recorder(recorder_id)
        logger.debug(
            f"Will receive a file {file_rel_path} ({file_size / 2 ** 20:.2f}MB) from recorder {recorder_id}:{kin_alias}")

    def comm_file_receive_update(self, recorder_id: int, file_rec_id: int, file_rel_path: str, size_curr_received: int,
            size_already_received: int):
        self._recordings_received_size[file_rec_id] += size_curr_received
        curr_timestamp = time.time()
        if self._recordings_received_last_timestamp[file_rec_id] < int(curr_timestamp) - self._receive_speed_timeframe:
            self._recordings_received_last_timestamp[file_rec_id] = int(curr_timestamp)
            self._recordings_received_last_size[file_rec_id][:] = 0
        else:
            while self._recordings_received_last_timestamp[file_rec_id] < int(curr_timestamp):
                self._recordings_received_last_timestamp[file_rec_id] += 1
                self._recordings_received_last_size[file_rec_id] = np.roll(self._recordings_received_last_size[file_rec_id], -1)
                self._recordings_received_last_size[file_rec_id][-1] = 0
        self._recordings_received_last_size[file_rec_id][-1] += size_curr_received
        received_percent = self._recordings_received_size[file_rec_id] / self._recordings_database[
            file_rec_id].size * 100
        avg_speed = self._recordings_received_last_size[file_rec_id].sum() / (
                    self._receive_speed_timeframe - 1 + np.modf(curr_timestamp)[0])
        logger.debug(f"Recording {file_rec_id}: received {self._recordings_received_size[file_rec_id] / 2 ** 20:.2f}MB/"
                     f"{self._recordings_database[file_rec_id].size / 2 ** 20:.2f}MB ({received_percent:.1f}%), "
                     f"(speed is {avg_speed / 2 ** 20:.2f} MB/s)")
        # TODO: add view callback

    def comm_file_receive_end(self, recorder_id: int, file_rec_id: int, file_rel_path: str, file_size: int,
            file_received: int):
        kin_alias = self.kinect_alias_from_recorder(recorder_id)
        if file_size != file_received:
            logger.error(
                f"Received a corrupt file from {recorder_id}:{kin_alias}: {file_rel_path}, "
                f"received {file_received / 2 * 20:.2f}MB, expected {file_size / 2 * 20:.2f}MB")
        else:
            logger.info(f"Received a file from {recorder_id}:{kin_alias}: {file_rel_path}")
