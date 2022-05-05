import time

import websockets
import asyncio
import logging
import json
from multiprocessing import Process, Queue as MPQueue


logger = logging.getLogger("KR.nethandler")


class NetHandler:
    class StopEvent:
        pass

    class ConnectedEvent:
        pass

    def __init__(self, server: str = "kinrec.cv:4400", queue_size: int = 100, outqueue_delay=1e-2):
        self.serveraddr = server
        self._in_queue = MPQueue(maxsize=queue_size)
        self._out_queue = MPQueue(maxsize=queue_size)
        self._is_active = False
        self._main_active = False
        self._websocket = None
        self.process = None
        self.outqueue_delay = outqueue_delay

    def start(self):
        self.process = Process(target=self._main)
        logger.info("Starting the new process")
        self.process.start()
        logger.info("Waiting for the new process to connect")
        event = self._in_queue.get()
        if isinstance(event, self.ConnectedEvent):
            self._main_active = True
            return "OK"
        else:
            raise event

    def close(self):
        logger.info("Sending the stop message to the loop")
        self._out_queue.put(self.StopEvent())
        self._close_root()

    def _close_root(self):
        self.process.join()
        logger.info("Closing the pipes (root)")
        self._main_active = False
        self._in_queue.close()
        self._out_queue.close()

    @property
    def active(self) -> bool:
        return self._main_active

    def get(self, wait: bool = False):
        if not wait and self._in_queue.empty():
            return None
        else:
            msg = self._in_queue.get()
            if isinstance(msg, str):
                msg = json.loads(msg)
            elif isinstance(msg, self.StopEvent):
                self._close_root()
                return None
            return msg

    def send(self, data):
        if isinstance(data, dict):
            data = json.dumps(data)
        self._out_queue.put(data)

    def _main(self):
        asyncio.get_event_loop().run_until_complete(self._loop())
        logger.info("Child process completed")

    async def _out_queue_handler(self):
        while self._is_active:
            if self._out_queue.empty():
                await asyncio.sleep(self.outqueue_delay)
            else:
                msg = self._out_queue.get()
                if isinstance(msg, self.StopEvent):
                    logger.info("Got the Stop message, shutting the loop down")
                    self._is_active = False
                    self._stop_event.set()
                else:
                    try:
                        await self._websocket.send(msg)
                    except websockets.ConnectionClosed as e:
                        logger.info(f"Websocket connection is closed: {e}")
                        logger.info("Shutting the loop down")
                        self._in_queue.put(self.StopEvent())
                        self._is_active = False
                        self._stop_event.set()

    async def _in_queue_handler(self):
        while self._is_active:
            try:
                msg = await self._websocket.recv()
                logger.info(f"Received: {msg}")
            except websockets.ConnectionClosed as e:
                logger.info(f"Websocket connection is closed: {e}")
                logger.info("Shutting the loop down")
                self._in_queue.put(self.StopEvent())
                self._is_active = False
                self._stop_event.set()
            else:
                self._in_queue.put(msg)

    async def _loop(self):
        connected = False
        while not connected:
            try:
                logger.info("Trying to connect WS")
                self._websocket = await websockets.connect("ws://" + self.serveraddr)
            except ConnectionRefusedError as e:
                logger.info("Connection refused, trying again")
                time.sleep(2)
            except Exception as e:
                logger.error(f"Failed to connect to {self.serveraddr}: {e}")
                self._in_queue.put(e)
                connected = True
            else:
                connected = True
                self._is_active = True
                self._stop_event = asyncio.Event()
                logger.info(f"Connected to {self.serveraddr} successfully")
                self._in_queue.put(self.ConnectedEvent())
                logger.info("Starting the handler loop")
                asyncio.create_task(self._in_queue_handler())
                asyncio.create_task(self._out_queue_handler())
                await self._stop_event.wait()
                logger.info("Waiting for WS to close")
                await self._websocket.close()
        logger.info("Closing the pipes (child)")
        self._in_queue.close()
        self._out_queue.close()
