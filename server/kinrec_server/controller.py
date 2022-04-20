import asyncio

import numpy as np
import logging
import os
import time
import websockets
from recorder_communication import RecorderComm
from typing import Dict, Optional, Union, Sequence, Mapping

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("controller")


class MainController:
    def __init__(self, server_address="kinrec.cv:4400", kinect_id_mapping: Dict[str, int] = None):
        self.server_address = server_address
        self._next_recorder_id = 0
        self._connected_recorders = {}
        self._connected_recorder_tasks = {}
        self._loop_active = False
        self._kinect_id_mapping = kinect_id_mapping
        self._loop_sleep = 0.5
        self._view_recorders_placement = {} #recorder_id:position_in_the_view

    async def handle_new_recorder_connection(self, websocket):
        comm = RecorderComm(websocket, self, self._next_recorder_id)
        comm_task = asyncio.create_task(comm.start_event_loop())
        self._connected_recorders[self._next_recorder_id] = comm
        self._connected_recorder_tasks[self._next_recorder_id] = comm_task
        logger.info(f"Created a new recorder ID {self._next_recorder_id}")
        self._next_recorder_id += 1

    async def recorder_server_loop(self):
        host, port = self.server_address.split(":")
        async with websockets.serve(self.handle_new_recorder_connection, host, int(port)):
            await asyncio.Future()

    async def main_loop(self):
        asyncio.create_task(self.recorder_server_loop())
        while self._loop_active:
            await asyncio.sleep(self._loop_sleep)

    def start(self):
        self._loop_active = True
        asyncio.get_event_loop().run_until_complete(self.main_loop())

    def stop(self):
        self._loop_active = False

    ### Actions ###
    def update_kinect_status(self, recorder_id: int, kinect_status: str, recorder_transferring: bool,
        status_info: str, optionals: Dict[str, Union[float, Dict[str, float]]]):
        pass



    ### Callbacks ###
    def comm_get_status_reply(self, recorder_id: int, reply_result: bool, kinect_status: str,
            recorder_transferring: bool, status_info: str, optionals: Dict[str, Union[float, Dict[str, float]]],
            info: str = None):
        pass

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

