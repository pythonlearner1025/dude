import asyncio

import numpy as np
import pytest
from aiohttp import ClientSession, web

from m8py.listen import remote_mic_app
from m8py.speaking import Speaking


class Listener:
    def __init__(self):
        self.chunks = []
        self.active = False

    async def feed_pcm(self, chunk, muted=False):
        self.chunks.append((chunk, muted))
        self.active = True

    async def feed(self, chunk, muted=False):
        self.chunks.append((np.asarray(chunk), muted))
        if muted:
            self.active = False

    def speech_active(self):
        return self.active


class Link:
    def __init__(self):
        self.mic_muted = False
        self.sent = []

    async def send_json(self, value):
        self.sent.append(value)


@pytest.mark.asyncio
async def test_remote_websocket_barge_in_interrupts_speech(cfg):
    cfg.mic.source = "remote"
    cfg.mic.barge_in = True
    listener = Listener()
    speaking = Speaking()
    speaking.extend(1)
    link = Link()
    runner = web.AppRunner(await remote_mic_app(listener, speaking, link, cfg))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    async with ClientSession() as client:
        async with client.ws_connect(f"http://127.0.0.1:{port}/mic") as ws:
            await ws.send_bytes(b"\x00\x00" * 512)
            for _ in range(20):
                if link.sent:
                    break
                await asyncio.sleep(0.01)

    await runner.cleanup()
    assert speaking.generation == 1
    assert link.sent == [{"type": "stop_audio"}]
    assert listener.chunks == [(b"\x00\x00" * 512, False)]
