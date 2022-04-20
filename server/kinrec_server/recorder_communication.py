import asyncio
import numpy as np
import json
import time
import logging
import base64
import io
import os
from PIL import Image
from collections import namedtuple
from functools import partial
from typing import Optional, Union, List, Sequence

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recorder_comm")


class RecorderComm:
    class UnmatchedAnswerException(Exception):
        def __init__(self, cmd_report):
            super().__init__()
            self.cmd_report = cmd_report
    class FileReceiveException(Exception):
        pass
    ControllerCallbacks = namedtuple("ControllerCallbacks", "set_status set_calibration set_kinect_params_reply ")
    unmatched_answers = ["collect_file_start", "collect_file_end"]

    def __init__(self, websocket, controller, recorder_id, fields_ttl = 100.):
        self._recorder_id = recorder_id
        self._websocket = websocket
        self._kinect_id = None
        self._kinect_calibration = None
        self._recordings_list = None
        self._sent_cmds = []
        self._kinect_status = "disconnected"
        self._recorder_transferring = False
        self._fields_ttl = fields_ttl
        self._recording_paths = {}
        self._current_file_descriptor = None
        self._current_file_size = None
        self._current_file_received = None
        self._current_file_rel_path = None
        self._current_file_rec_id = None
        # self.controller_callbacks: RecorderComm.ControllerCallbacks = None
        self._register_callbacks(controller)

    def _register_callbacks(self, controller):
        self.controller_callbacks = self.ControllerCallbacks(
            partial(controller.comm_set_recorder_status, self._recorder_id),

        )

    def _match_answer(self, cmd_report):
        cmdt = cmd_report["cmd"]
        if cmdt not in self.unmatched_answers:
            for sent_ind, (sent_cmdt, sent_waiting_event) in enumerate(self._sent_cmds):
                if cmdt == sent_cmdt:
                    self._sent_cmds.remove(sent_cmdt)
                    return sent_waiting_event
            raise RecorderComm.UnmatchedAnswerException(cmd_report)
        else:
            return None

    async def process_events(self):
        # if self._kinect_id is None:
        #     self._init_kinect_info()
        msg = await self._websocket.recv()
        if isinstance(msg, dict):
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

                    if self._kinect_id is None and cmdt not in ["get_kinect_calibration", "get_status"]:
                        logger.error(f"Received {cmdt} before obtaining Kinect info")
                        return

                    if cmdt == "get_status":
                        self._kinect_status = msg["kinect_status"]
                        self._recorder_transferring = msg["transferring"]
                        self.controller_callbacks.get_status_reply(True, self._kinect_status, self._recorder_transferring, msg["info"], msg["optionals"])
                    elif cmdt == "get_kinect_calibration":
                        if cmd_result == "OK":
                            self._kinect_id = msg["kinect_id"]
                            self._kinect_calibration = msg["kinect_calibration"]
                            logger.info(f"Got info from Kinect: id {self._kinect_id}")
                            self.controller_callbacks.get_kinect_calibration_reply(True, self._kinect_id, self._kinect_calibration)
                        else:
                            self.controller_callbacks.get_kinect_calibration_reply(False, None, None, info=cmd_info)
                    elif cmdt == "set_kinect_params":
                        self.controller_callbacks.set_kinect_params_reply(True)
                    elif cmdt == "start_preview":
                        self.controller_callbacks.start_preview_reply(cmd_result == "OK",
                                                                     info=None if cmd_result == "OK" else cmd_info)
                    elif cmdt == "get_preview_frame":
                        if cmd_result == "OK":
                            data = msg["data"]
                            data = base64.b64decode(data.encode("utf-8"))
                            img = np.array(Image.open(data, formats=["jpeg"]))
                            timestamp = msg["timestamp"]
                            self.controller_callbacks.get_preview_frame_reply(True, img, timestamp)
                        else:
                            self.controller_callbacks.get_preview_frame_reply(False, info=cmd_info)
                    elif cmdt == "stop_preview":
                        self.controller_callbacks.stop_preview_reply(cmd_result == "OK",
                                                                     info = None if cmd_result == "OK" else cmd_info)
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
                        self.controller_callbacks.collect_reply(cmd_result == "OK",
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
                    self._current_file_rel_path = msg["relative_file_path"]
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
                self.controller_callbacks.file_receive_update(self._current_file_received)

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
                                                   self._current_file_size)
        self._current_file_received = 0
        self._current_file_size = None
        self._current_file_rec_id = None
        self._current_file_rel_path = None

    @property
    async def kinect_id(self) -> str:
        event = asyncio.Event()
        await self._send({"type": "get_kinect_calibration"}, event)
        await event.wait()
        return self._kinect_id

    async def set_kinect_params(self, rgb_res, depth_wfov, depth_binned, fps, sync_mode):
        await self._send({"type": "set_kinect_params", "rgb_res":rgb_res, 'depth_wfov':depth_wfov,
                          'depth_binned': depth_binned, 'fps': fps, 'sync_mode':sync_mode})

    async def get_kinect_calibration(self):
        await self._send({"type": "get_kinect_calibration"})

    async def get_status(self, disk_space = False, battery = False, recording_fps = False):
        optionals = []
        if disk_space:
            optionals.append("disk_space")
        if battery:
            optionals.append("battery")
        if recording_fps:
            optionals.append("recording_fps")
        await self._send({"type": "get_status", "optionals": optionals})

    async def start_preview(self):
        await self._send({"type": "start_preview"})

    async def get_preview_frame(self, scale:Union[float, int] = 1):
        await self._send({"type": "get_preview_frame", "scale": scale})

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

    async def collect(self, recording_id):
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
        await self._websocket.send(data)

    def _init_kinect_info(self):
        self._send({"type": "get_kinect_calibration"})





