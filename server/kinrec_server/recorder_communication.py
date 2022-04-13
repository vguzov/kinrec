import asyncio
import numpy as np
import json
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recorder_comm")


class RecorderComm:
    unmatched_answers = ["collect_file_start", "collect_file_end"]
    def __init__(self, websocket, fields_ttl = 100.):
        self._websocket = websocket
        self._kinect_id = None
        self._kinect_calibration = None
        self._recordings_list = None
        self._sent_cmds = []
        self._kinect_status = "disconnected"
        self._recorder_transferring = False
        self._fields_ttl = fields_ttl

    def _match_answer(self, cmd_report):
        cmdt = cmd_report["cmd"]
        if cmdt not in self.unmatched_answers:
            for sent_ind, sent_cmdt in enumerate(self._sent_cmds):
                if cmdt == sent_cmdt:
                    self._sent_cmds.remove(sent_cmdt)
                    return True
            logger.error(f"Received unexpected answer {cmd_report}")
            return False
        else:
            return True

    def process_events(self):
        if self._kinect_id is None:
            self._init_kinect_info()
        msg = await self._websocket.recv()
        if isinstance(msg, dict):
            cmd_report = msg['cmd_report']
            self._match_answer(cmd_report)
            cmdt = cmd_report["cmd"]
            if cmd_report["result"] != "OK":
                logger.error(f"Error on recorder: {cmd_report}")
                return
            else:
                logger.info(f"{cmdt} -- OK")

            if cmdt == "get_status":
                self._kinect_status = msg["kinect_status"]
                self._recorder_transferring = msg["transferring"]
            elif cmdt == "get_kinect_calibration":
                self._kinect_id = msg["kinect_id"]
                self._kinect_calibration = msg["kinect_calibration"]
                logger.info(f"Got info from Kinect: id {self._kinect_id}")


    def _send(self, data):
        if isinstance(data, dict):
            logger.info(f"Sending '{data['type']}'")
            self._sent_cmds.append(data['type'])
            data = json.dumps(data)
        await self._websocket.send(data)

    def _init_kinect_info(self):
        self._send({"type": "get_kinect_calibration"})





