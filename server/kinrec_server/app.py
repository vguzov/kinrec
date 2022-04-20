import tkinter as tk

from .view import KinRecView
from .controller import KinRecController
from .recorder_communication import RecorderComm
from .parameters import app_default_parameters

import logging
import asyncio
from functools import wraps
import websockets
from copy import deepcopy
import toml
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("application")

class KinRecApp(tk.Tk):
    def __init__(self, number_of_kinects, server_address="kinrec.cv:4400", workdir = "./kinrec"):
        super().__init__()
        self.server_address = server_address
        self._next_recorder_id = 0
        self._connected_recorders = {}
        self._connected_recorder_tasks = {}
        self._workdir = workdir
        self._loop_active = False
        self._kinect_id_mapping = {}
        self._loop_sleep = 1/30.
        self._status_update_period = 0.5

        os.makedirs(self._workdir, exist_ok=True)
        params_path = os.path.join(self._workdir, "params.toml")
        if os.path.isfile(params_path):
            parameters_dict = toml.load(open(params_path))
        else:
            parameters_dict = deepcopy(app_default_parameters)
            toml.dump(parameters_dict, open(params_path, "w"))

        self.title("Kinect Recorder server interface")

        self.controller = KinRecController()

        self.view = KinRecView(parent=self, number_of_kinects=number_of_kinects)
        self.view.set_controller(self.controller)
        self.controller.set_view(self.view)

    def start(self):
        self._loop_active = True
        asyncio.get_event_loop().run_until_complete(self.main_loop())

    def stop(self):
        self._loop_active = False

    def handle_closed_recorder(self, recorder_id):
        logger.info(f"Recorder {recorder_id} closed")
        self.controller.remove_recorder(recorder_id)
        del self._connected_recorders[recorder_id]
        del self._connected_recorder_tasks[recorder_id]

    async def handle_new_recorder_connection(self, websocket):
        recorder = RecorderComm(websocket, self, self._next_recorder_id,
                                connection_close_callback=self.handle_closed_recorder)
        recorder_task = asyncio.create_task(recorder.start_event_loop())
        recorder_id = self._next_recorder_id
        self._connected_recorders[recorder_id] = recorder
        self._connected_recorder_tasks[recorder_id] = recorder_task
        logger.info(f"Created a new recorder ID {recorder_id}")
        self.controller.add_recorder(recorder, recorder_id)
        self._next_recorder_id += 1

    async def recorder_server_loop(self, stop_event: asyncio.Event):
        host, port = self.server_address.split(":")
        async with websockets.serve(self.handle_new_recorder_connection, host, int(port)):
            await stop_event.wait()

    async def status_update_loop(self):
        while self._loop_active:
            self.controller.ask_kinect_status()
            await asyncio.sleep(self._status_update_period)

    async def main_loop(self):
        server_stop_event = asyncio.Event()
        asyncio.create_task(self.recorder_server_loop(server_stop_event))
        asyncio.create_task(self.status_update_loop())
        while self._loop_active:
            self.update()
            await asyncio.sleep(self._loop_sleep)
        server_stop_event.set()
