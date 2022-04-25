import asyncio

import numpy as np
import logging
import os
import time
import websockets
# import cv2
import matplotlib.cm
from skimage.io import imsave
from PIL import Image
from collections import defaultdict
from .recorder_communication import RecorderComm
from typing import Dict, Optional, Union, Sequence, Mapping
from .internal import RecorderState, KinectParams
from .view import KinRecView

logger = logging.getLogger("KRS.controller")


class KinRecController:
    def __init__(self, kinect_alias_mapping: Dict[Optional[str], Optional[int]] = None, preview_fps=10.):
        if kinect_alias_mapping is None:
            kinect_alias_mapping = defaultdict(lambda: None)
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
        self._recordings_list = {}
        self._recorder_reclist_responses = {}

    def kinect_alias(self, recorder_id: int) -> Optional[int]:
        return self._kinect_id_mapping[self._connected_recorders[recorder_id].kinect_id]

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

    def _compile_recordings_list(self, recorderwise_reclists: Dict[int, dict]):
        # TODO: complete the list compilation
        pass

    ### Actions ###
    def start_preview(self, recorder_id: int) -> bool:
        if recorder_id not in self._connected_recorders:
            logger.warning(f"A preview for recorder {recorder_id} was asked, but not such recorder exists")
            return False
        asyncio.create_task(self._start_preview(recorder_id))
        return True

    def stop_preview(self, recorder_id: int) -> bool:
        if recorder_id not in self._connected_recorders:
            logger.warning(f"A 'stop preview' for recorder {recorder_id} was asked, but not such recorder exists")
            return False
        asyncio.create_task(self._stop_preview(recorder_id))
        return True

    def apply_kinect_params(self, kinect_params: KinectParams):
        self._last_kinect_params = kinect_params
        recorder_ids = sorted(self._connected_recorders.keys())
        if len(recorder_ids) > 0:
            master_recorder = recorder_ids[0]
            for recorder_id, recorder in self._connected_recorders.items():
                sync_mode = "none"
                if kinect_params.sync:
                    if recorder_id == master_recorder:
                        sync_mode = "master"
                    else:
                        sync_mode = "sub"
                self._params_applied_responses[recorder_id] = None
                asyncio.create_task(recorder.set_kinect_params(kinect_params.rgb_res,
                                                               kinect_params.depth_wfov,
                                                               kinect_params.depth_binned,
                                                               kinect_params.fps, sync_mode))

    def collect_recordings_info(self):
        self._recordings_list = {}
        for recorder_id, recorder in self._connected_recorders.items():
            self._recorder_reclist_responses[recorder_id] = None
            asyncio.create_task(recorder.get_recordings_list())

    ### Methods ###
    def set_view(self, view: KinRecView):
        self._view = view
        self._view.update_server_state("online")

    async def add_recorder(self, recorder: RecorderComm, recorder_id: int):
        assert recorder_id not in self._connected_recorders
        self._connected_recorders[recorder_id] = recorder
        await recorder.get_kinect_calibration()
        current_params = self._last_kinect_params
        await recorder.set_kinect_params(current_params.rgb_res, current_params.depth_wfov,
                                         current_params.depth_binned, current_params.fps, "none")

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
        kin_alias = self.kinect_alias(recorder_id)
        self._connected_recorders[recorder_id].set_kinect_alias(kin_alias)
        if not reply_result:
            logger.warning(f"Recorder {recorder_id}:{kin_alias} Failed to obtain kinect calibration, more info: {info}")

    def comm_set_kinect_params_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        self._params_applied_responses[recorder_id] = reply_result
        if not reply_result:
            kin_alias = self.kinect_alias(recorder_id)
            logger.warning(f"Recorder {recorder_id}:{kin_alias} Failed to set parameters, more info: {info}")
        responses = list(self._params_applied_responses.values())
        done_responses = [x is not None for x in responses]
        if all(done_responses):
            self._view.params_apply_finalize(all(responses))

    def comm_start_preview_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        if reply_result:
            self._view.start_preview(recorder_id)
        else:
            kin_alias = self.kinect_alias(recorder_id)
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
            kin_alias = self.kinect_alias(recorder_id)
            logger.warning(f"Recorder {recorder_id}:{kin_alias} Preview failed to stop, more info: {info}")

    def comm_start_recording_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_stop_recording_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_get_recordings_list_reply(self, recorder_id: int, reply_result: bool, recordings: Dict[int, dict] = None,
            info: str = None):
        if reply_result:
            self._recorder_reclist_responses[recorder_id] = recordings
        else:
            self._recorder_reclist_responses[recorder_id] = {}
            kin_alias = self.kinect_alias(recorder_id)
            logger.warning(
                f"Recorder {recorder_id}:{kin_alias} Preview failed to acquire recordings, more info: {info}")
        replies = list(self._recorder_reclist_responses.values())
        completed_replies = [x is not None for x in replies]
        if all(completed_replies):
            self._compile_recordings_list(self._recorder_reclist_responses)

    def comm_collect_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_delete_recording_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_stop_collect_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_shutdown_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_reboot_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_file_receive_start(self, recorder_id: int, file_rec_id: int, file_rel_path: str, file_size: int):
        pass

    def comm_file_receive_update(self, recorder_id: int, file_rec_id: int, file_rel_path: str, file_curr_received: int):
        pass

    def comm_file_receive_end(self, recorder_id: int, file_rec_id: int, file_rel_path: str, file_size: int,
            file_received: int):
        pass
