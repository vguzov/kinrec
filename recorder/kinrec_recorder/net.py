import websockets
import asyncio
import logging
import json
from multiprocessing import Process, Queue as MPQueue


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nethandler")


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
            return "OK"
        else:
            raise event

    def close(self):
        logger.info("Sending the stop message to the loop")
        self._out_queue.put(self.StopEvent())
        self.process.join()
        logger.info("Closing the pipes (root)")
        self._in_queue.close()
        self._out_queue.close()

    def get(self, wait: bool = False):
        if not wait and self._in_queue.empty():
            return None
        else:
            return self._in_queue.get()

    def send(self, data):
        if isinstance(data, dict):
            data = json.dumps(data)
        self._out_queue.put(data)

    def _main(self):
        asyncio.run(self._loop())
        logger.info("Child process completed")

    async def _out_queue_handler(self):
        if self._out_queue.empty():
            await asyncio.sleep(self.outqueue_delay)
        else:
            msg = self._out_queue.get()
            if isinstance(msg, self.StopEvent):
                logger.info("Got the Stop message, shutting the loop down")
                self._is_active = False
            else:
                await self._websocket.send(msg)

    async def _in_queue_handler(self):
        msg = await self._websocket.recv()
        self._in_queue.put(msg)

    async def _loop(self):
        try:
            logger.info("Trying to connect WS")
            self._websocket = await websockets.connect("ws://" + self.serveraddr)
        except Exception as e:
            logger.error(f"Failed to connect to {self.serveraddr}: {e}")
            self._in_queue.put(e)
        else:
            self._is_active = True
            logger.info(f"Connected to {self.serveraddr} successfully")
            self._in_queue.put(self.ConnectedEvent())
            logger.info("Starting the handler loop")
            while self._is_active:
                await self._in_queue_handler()
                await self._out_queue_handler()
            logger.info("Waiting for WS to close")
            await self._websocket.close()
        logger.info("Closing the pipes (child)")
        self._in_queue.close()
        self._out_queue.close()
