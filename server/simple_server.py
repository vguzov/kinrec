#!/usr/bin/env python

import asyncio
import websockets
import sys
import functools
import json

async def input_sender(raw_input, websocket):
    while True:
        msg = await raw_input('>> ')
        await websocket.send(msg)


async def echo(websocket):
    print(f"Connection opened {websocket}")
    prompt = Prompt()
    raw_input = functools.partial(prompt, end='', flush=True)
    asyncio.create_task(input_sender(raw_input, websocket))
    async for message in websocket:
        print("<< "+message)
        # await websocket.send(message)

class Prompt:
    def __init__(self, loop=None):
        self.loop = loop or asyncio.get_event_loop()
        self.q = asyncio.Queue()
        self.loop.add_reader(sys.stdin, self.got_input)

    def got_input(self):
        asyncio.ensure_future(self.q.put(sys.stdin.readline()), loop=self.loop)

    async def __call__(self, msg, end='\n', flush=False):
        print(msg, end=end, flush=flush)
        return (await self.q.get()).rstrip('\n')



async def main():
    async with websockets.serve(echo, "192.168.1.40", 4400):
        await asyncio.Future()  # run forever

asyncio.run(main())