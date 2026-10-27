from __future__ import annotations

import asyncio
import json
import struct
from collections import deque
from typing import Awaitable, Callable

import httpx
import numpy as np
from aiohttp import WSMsgType, web

from .config import Config
from .link import GameLink
from .speaking import Speaking
from .trace import Trace, now_ms

SAMPLE_RATE, VAD_WINDOW = 16000, 512
MARGIN_BEFORE, MARGIN_AFTER, KEPT = 3200, 1600, 400000


def wav(samples: np.ndarray | list[float], rate: int = SAMPLE_RATE) -> bytes:
    arr = np.asarray(samples, dtype=np.float32)
    pcm = (np.clip(arr, -1, 1) * 32767).astype("<i2").tobytes()
    size = len(pcm)
    return (
        b"RIFF"
        + struct.pack("<I", 36 + size)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", size)
        + pcm
    )


def decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV")
    at = 12
    fmt = (1, 1, 16000, 16)
    raw = b""
    while at + 8 <= len(data):
        kind = data[at : at + 4]
        size = int.from_bytes(data[at + 4 : at + 8], "little")
        chunk = data[at + 8 : at + 8 + size]
        if kind == b"fmt " and len(chunk) >= 16:
            fmt = (
                int.from_bytes(chunk[:2], "little"),
                int.from_bytes(chunk[2:4], "little"),
                int.from_bytes(chunk[4:8], "little"),
                int.from_bytes(chunk[14:16], "little"),
            )
        elif kind == b"data":
            raw = chunk
        at += 8 + size + size % 2
    form, channels, rate, bits = fmt
    if (form, bits) == (1, 16):
        arr = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    elif (form, bits) == (3, 32):
        arr = np.frombuffer(raw, dtype="<f4").astype(np.float32)
    else:
        raise ValueError("a WAV of 16-bit or float samples, please")
    if channels > 1:
        arr = arr[: len(arr) // channels * channels].reshape(-1, channels).mean(axis=1)
    return arr, rate


def resample(samples: np.ndarray, source: int, target: int = SAMPLE_RATE) -> np.ndarray:
    if source == target or not len(samples):
        return samples.astype(np.float32, copy=False)
    n = round(len(samples) * target / source)
    return np.interp(np.arange(n) * source / target, np.arange(len(samples)), samples).astype(
        np.float32
    )


class Transcriber:
    def __init__(
        self, url: str, model: str | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self.url, self.model, self.client = url, model, client or httpx.AsyncClient(timeout=30)

    async def transcribe(self, samples: np.ndarray | list[float]) -> str:
        data = {"model": self.model} if self.model else {}
        response = await self.client.post(
            self.url, data=data, files={"file": ("speech.wav", wav(samples), "audio/wav")}
        )
        response.raise_for_status()
        return str(response.json().get("text", "")).strip()


class Listener:
    """Silero VAD wrapper; injection points keep tests and remote/local sources identical."""

    def __init__(
        self,
        cfg: Config,
        transcriber: Transcriber,
        input_rate: int,
        output: Callable[[str, dict[str, float], str], Awaitable[None]],
        trace: Trace | None = None,
    ) -> None:
        self.cfg, self.transcriber, self.input_rate, self.output, self.trace = (
            cfg,
            transcriber,
            input_rate,
            output,
            trace,
        )
        self.pending = np.empty(0, np.float32)
        self.kept = deque(maxlen=KEPT)
        self.speech = bytearray()
        self.active = False
        self.silence = 0
        self.accepted = 0
        self.vad_origin = 0
        self.threshold = cfg.mic.vad_threshold
        self._vad = self._create_vad()

    def _create_vad(self):
        try:
            import sherpa_onnx

            c = sherpa_onnx.VadModelConfig()
            c.silero_vad.model = str(self.cfg.models.silero_vad)
            c.silero_vad.threshold = self.cfg.mic.vad_threshold
            c.silero_vad.min_silence_duration = self.cfg.mic.end_of_speech_silence
            c.silero_vad.min_speech_duration = 0.0
            c.silero_vad.max_speech_duration = 20.0
            c.silero_vad.window_size = VAD_WINDOW
            c.sample_rate = SAMPLE_RATE
            return sherpa_onnx.VoiceActivityDetector(c, 60)
        except Exception:
            return None

    async def feed_pcm(self, pcm: bytes, muted: bool = False) -> None:
        samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768
        await self.feed(samples, muted)

    async def feed(self, chunk: np.ndarray, muted: bool = False) -> None:
        if muted:
            self.pending = np.empty(0, np.float32)
            self.active = False
            if self._vad is not None:
                self._vad.reset()
                self.vad_origin = self.accepted
            return
        samples = resample(np.asarray(chunk, dtype=np.float32), self.input_rate)
        self.pending = np.concatenate((self.pending, samples))
        while len(self.pending) >= VAD_WINDOW:
            window = self.pending[:VAD_WINDOW]
            self.pending = self.pending[VAD_WINDOW:]
            self.kept.extend(window.tolist())
            self.accepted += VAD_WINDOW
            if self._vad is not None:
                self._vad.accept_waveform(window.tolist())
                while not self._vad.empty():
                    seg = self._vad.front
                    start = self.vad_origin + max(0, int(seg.start))
                    segment = np.asarray(seg.samples, dtype=np.float32).copy()
                    self._vad.pop()
                    kept_from = max(0, self.accepted - len(self.kept))
                    begin = max(kept_from, start - MARGIN_BEFORE)
                    end = min(self.accepted, start + len(segment) + MARGIN_AFTER)
                    kept = np.asarray(self.kept, dtype=np.float32)
                    audio = (
                        kept[begin - kept_from : end - kept_from]
                        if begin < end and start >= kept_from
                        else segment
                    )
                    await self._recognize(audio)
            else:
                loud = float(np.sqrt(np.mean(window * window))) > 0.015
                if loud:
                    if not self.active:
                        self.speech.extend(
                            np.asarray(list(self.kept)[-MARGIN_BEFORE:], dtype=np.float32).tobytes()
                        )
                    self.active = True
                    self.silence = 0
                    self.speech.extend(window.tobytes())
                elif self.active:
                    self.silence += VAD_WINDOW
                    self.speech.extend(window.tobytes())
                    if self.silence >= int(self.cfg.mic.end_of_speech_silence * SAMPLE_RATE):
                        audio = np.frombuffer(self.speech, dtype=np.float32).copy()
                        self.speech.clear()
                        self.active = False
                        await self._recognize(audio)

    def speech_active(self) -> bool:
        return bool(self._vad.is_speech_detected() if self._vad is not None else self.active)

    async def _recognize(self, audio: np.ndarray) -> None:
        turn_id = f"{now_ms()}-mic"
        started = asyncio.get_running_loop().time()
        text = await self.transcriber.transcribe(audio)
        elapsed = (asyncio.get_running_loop().time() - started) * 1000
        if self.trace and self.trace.session_dir.joinpath("audio").exists():
            self.trace.session_dir.joinpath("audio", f"{turn_id}-mic.wav").write_bytes(wav(audio))
        if text:
            timing = {
                "vad_speech_start": -elapsed - len(audio) / SAMPLE_RATE * 1000,
                "vad_speech_end": -elapsed,
                "stt_done": 0.0,
            }
            await self.output(text, timing, turn_id)


async def remote_mic_app(listener: Listener) -> web.Application:
    app = web.Application()

    async def mic(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        ptt = True
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                await listener.feed_pcm(msg.data, muted=not ptt)
            elif msg.type == WSMsgType.TEXT:
                try:
                    value = json.loads(msg.data)
                    if value.get("type") == "ptt":
                        ptt = bool(value.get("down"))
                except ValueError:
                    pass
        return ws

    app.router.add_get("/mic", mic)
    return app


async def run_local(listener: Listener, speaking: Speaking, link: GameLink) -> None:
    import sounddevice as sd

    loop = asyncio.get_running_loop()
    q: asyncio.Queue[np.ndarray] = asyncio.Queue()
    device = sd.query_devices(kind="input")
    rate = int(device["default_samplerate"])
    listener.input_rate = rate

    def callback(indata, frames, timing, status):
        loop.call_soon_threadsafe(q.put_nowait, np.asarray(indata).mean(axis=1).copy())

    with sd.InputStream(callback=callback, samplerate=rate):
        while True:
            chunk = await q.get()
            talking = speaking.is_speaking()
            await listener.feed(
                chunk,
                link.mic_muted
                or (
                    not listener.cfg.mic.barge_in
                    and listener.cfg.mic.mute_while_speaking
                    and talking
                ),
            )
            if listener.cfg.mic.barge_in and talking and listener.speech_active():
                speaking.interrupt()
                await link.send_json({"type": "stop_audio"})
