import asyncio
import time
from types import SimpleNamespace

import pytest
from aiohttp import ClientSession, web

from m8py.brain import Event, Heard, PromptFile
from m8py.site import create_app
from m8py.trace import Trace


@pytest.mark.asyncio
async def test_site_inputs_record_absolute_receipt_time(tmp_path):
    trace = Trace(tmp_path / "logs")
    prompt = PromptFile(tmp_path / "prompt.txt")
    inputs = asyncio.Queue()
    link = SimpleNamespace(state=None)
    runner = web.AppRunner(create_app(trace, prompt, prompt, prompt, link, inputs))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    before = time.monotonic()

    async with ClientSession() as client:
        await client.post(f"http://127.0.0.1:{port}/say", data="hello")
        await client.post(f"http://127.0.0.1:{port}/event", data="incoming")

    heard = await inputs.get()
    event = await inputs.get()
    await runner.cleanup()
    assert isinstance(heard, Heard) and heard.timing["stt_done_at"] >= before
    assert isinstance(event, Event) and event.timing["event_received_at"] >= before
