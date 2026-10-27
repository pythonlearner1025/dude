import asyncio
import builtins

import numpy as np
import pytest
from aiohttp import ClientSession, web

from m8py.listen import Listener as RealListener
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


class Transcriber:
    async def transcribe(self, audio):
        return "testing"


def test_silero_load_failure_names_model(cfg, monkeypatch):
    cfg.mic.vad = "silero"
    real_import = builtins.__import__

    def fail_sherpa(name, *args, **kwargs):
        if name == "sherpa_onnx":
            raise OSError("cannot load model")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_sherpa)

    with pytest.raises(RuntimeError, match=str(cfg.models.silero_vad)):
        RealListener(cfg, object(), 16000, object())


def test_energy_vad_is_explicit_fallback(cfg):
    cfg.mic.vad = "energy"
    listener = RealListener(cfg, object(), 16000, object())
    assert listener._vad is None


@pytest.mark.asyncio
async def test_stt_prints_short_timing_line(cfg, capsys):
    cfg.mic.vad = "energy"
    heard = []

    async def output(text, timing, turn_id):
        heard.append(text)

    listener = RealListener(cfg, Transcriber(), 16000, output)
    await listener._recognize(np.zeros(1600, np.float32))

    assert heard == ["testing"]
    line = capsys.readouterr().out.strip()
    assert line.startswith('[stt] "testing" (') and line.endswith(" ms)")


@pytest.mark.asyncio
async def test_remote_websocket_barge_in_interrupts_speech(cfg, capsys):
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
    assert "[mic] barge-in" in capsys.readouterr().out
