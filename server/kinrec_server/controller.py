import asyncio

import numpy as np
import logging
import os
import time
import websockets
from .recorder_communication import RecorderComm
from typing import Dict, Optional, Union, Sequence, Mapping
from .internal import RecorderState
from .view import KinRecView

logger = logging.getLogger("KRS.controller")


class KinRecController:
    def __init__(self, kinect_id_mapping: Dict[str, int] = None):
        self._kinect_id_mapping = kinect_id_mapping
        self._view: Optional[KinRecView] = None
        self._connected_recorders = {}

    def set_view(self, view):
        self._view = view

    def add_recorder(self, recorder_comm, recorder_id):
        assert recorder_id not in self._connected_recorders
        self._connected_recorders[recorder_id] = recorder_comm

    def remove_recorder(self, recorder_id):
        del self._connected_recorders[recorder_id]

    ### Actions ###

    ### Methods ###
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
        pass

    def comm_set_kinect_params_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_start_preview_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_get_preview_frame_reply(self, recorder_id: int, reply_result: bool, img: np.ndarray, timestamp: int,
            info: str = None):
        pass

    def comm_stop_preview_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_start_recording_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_stop_recording_reply(self, recorder_id: int, reply_result: bool, info: str = None):
        pass

    def comm_get_recordings_list_reply(self, recorder_id: int, reply_result: bool, recordings: Dict[int, dict] = None,
            info: str = None):
        pass

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
