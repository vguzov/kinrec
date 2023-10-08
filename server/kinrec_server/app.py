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
from collections import defaultdict

logger = logging.getLogger("KRS.application")


class KinRecApp(tk.Tk):
    NET_MESSAGE_MAX_SIZE = 100 * 2 ** 20  # 100 MB
    def __init__(self, number_of_kinects: int, server_address: str = "kinrec.cv:4400", workdir: str = "./kinrec",
            status_update_period: float = 2.0):
        super().__init__()
        self.server_address = server_address
        self._connected_recorders = {}
        self._connected_recorder_tasks = {}
        self._workdir = workdir
        self._loop_active = False
        self._kinect_id_mapping = {}
        self._loop_sleep = 1 / 30.
        self._status_update_period = status_update_period
        self.protocol("WM_DELETE_WINDOW", self._on_quit)
        self._default_size = (420, 260 + 70 * number_of_kinects)

        os.makedirs(self._workdir, exist_ok=True)
        params_path = os.path.join(self._workdir, "params.toml")
        if os.path.isfile(params_path):
            parameters_dict = toml.load(open(params_path))
        else:
            parameters_dict = deepcopy(app_default_parameters)
            toml.dump(parameters_dict, open(params_path, "w"))

        kinect_alias_mapping = defaultdict(lambda: None)
        if "kinect_alias_mapping" in parameters_dict:
            kinect_alias_mapping.update(parameters_dict["kinect_alias_mapping"])

        self.title("Kinect Recorder server interface")

        self.controller = KinRecController(kinect_alias_mapping=kinect_alias_mapping)

        self.view = KinRecView(parent=self, number_of_kinects=number_of_kinects)
        self.view.set_controller(self.controller)
        self.controller.set_view(self.view)

        # default size
        self.minsize(*self._default_size)
        self.geometry("{}x{}".format(*self._default_size))

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

    @property
    def _next_recorder_id(self):
        ind = 0
        while ind in self._connected_recorders:
            ind += 1
        return ind

    async def handle_new_recorder_connection(self, websocket):
        recorder = RecorderComm(websocket, self.controller, self._next_recorder_id,
                                connection_close_callback=self.handle_closed_recorder)
        # recorder_task = asyncio.create_task()
        recorder_id = self._next_recorder_id
        self._connected_recorders[recorder_id] = recorder
        self._connected_recorder_tasks[recorder_id] = None
        logger.info(f"Created a new recorder ID {recorder_id}")
        await self.controller.add_recorder(recorder, recorder_id)
        await recorder.event_loop()

    async def recorder_server_loop(self, stop_event: asyncio.Event):
        host, port = self.server_address.split(":")
        async with websockets.serve(self.handle_new_recorder_connection, host, int(port), max_size=self.NET_MESSAGE_MAX_SIZE):
            await stop_event.wait()

    async def status_update_loop(self):
        while self._loop_active:
            await self.controller.ask_kinect_status()
            await asyncio.sleep(self._status_update_period)

    async def main_loop(self):
        server_stop_event = asyncio.Event()
        asyncio.create_task(self.recorder_server_loop(server_stop_event))
        asyncio.create_task(self.status_update_loop())
        while self._loop_active:
            try:
                self.update()
            except tk.TclError as e:
                logger.warning(f"TkInter failed to update with the following exception: '{e}'")
                self._loop_active = False
            else:
                await asyncio.sleep(self._loop_sleep)
        server_stop_event.set()

    def _on_quit(self):
        self._loop_active = False
