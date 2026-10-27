import asyncio

import httpx
import pytest

from m8py.speak import BreezeBackend, EndJob, SentenceJob, run
from m8py.speaking import Speaking
from m8py.trace import Trace


class Backend:
    sample_rate = 24000

    async def stream(self, text, how):
        yield b"\0\0" * 240


class Link:
    def __init__(self):
        self.said = []
        self.audio = []
        self.json = []

    async def say(self, x):
        self.said.append(x)

    async def send_audio(self, x):
        self.audio.append(x)

    async def send_json(self, x):
        self.json.append(x)


class OddChunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        for chunk in (b"\x01", b"\x02\x03\x04", b"\x05", b"\x06\x07\x08"):
            yield chunk


@pytest.mark.asyncio
async def test_breeze_stream_preserves_samples_split_across_chunks():
    async def handler(request):
        return httpx.Response(200, stream=OddChunks())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = BreezeBackend("http://tts", b"wav", "reference", 42, 24000, client)
        output = b"".join([chunk async for chunk in backend.stream("hello", "")])

    assert output == b"\x01\x02\x03\x04\x05\x06\x07\x08"


@pytest.mark.asyncio
async def test_interrupt_drops_stale_tts_jobs(tmp_path):
    speaking = Speaking()
    speaking.begin_line()
    speaking.interrupt()
    link = Link()
    trace = Trace(tmp_path / "logs")
    trace.start()
    q = asyncio.Queue()
    task = asyncio.create_task(run(Backend(), link, speaking, trace, q))
    await q.put(SentenceJob("stale", "", 0))
    await q.put(EndJob(0))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert link.said == [] and link.audio == []
    await trace.close()
