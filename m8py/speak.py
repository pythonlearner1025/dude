from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import time
from typing import AsyncIterator, Protocol

import httpx

from .config import Config
from .link import GameLink
from .listen import wav
from .speaking import Speaking
from .trace import Span, Trace

BREEZE_CFG = 4.0


class TTSBackend(Protocol):
    sample_rate: int
    async def stream(self, text: str, how: str) -> AsyncIterator[bytes]: ...


class BreezeBackend:
    def __init__(self, url: str, reference: bytes, reference_text: str, seed: int, sample_rate: int, client: httpx.AsyncClient) -> None:
        self.url, self.reference, self.reference_text, self.seed, self.sample_rate, self.client = url.rstrip("/"), reference, reference_text, seed, sample_rate, client

    @classmethod
    async def load(cls, cfg: Config, client: httpx.AsyncClient | None = None) -> BreezeBackend:
        path = cfg.mate.voice_reference
        if not path.exists(): raise FileNotFoundError(f"voice reference missing: {path}; create it with `m8py voice-design` or supply voices/soldier.wav")
        transcript = path.with_suffix(".txt")
        if not transcript.exists(): raise FileNotFoundError(f"voice transcript missing: {transcript}")
        client = client or httpx.AsyncClient(timeout=60)
        health = (await client.get(f"{cfg.mate.voice_server.rstrip('/')}/health")).json()
        if not isinstance(health.get("sample_rate"), int): raise RuntimeError("voice server sent no sample rate")
        return cls(cfg.mate.voice_server, path.read_bytes(), transcript.read_text().strip(), cfg.mate.voice_seed, health["sample_rate"], client)

    async def stream(self, text: str, how: str) -> AsyncIterator[bytes]:
        data = {"text": text, "cfg_scale": str(BREEZE_CFG if how else 1.0), "seed": str(self.seed), "ref_text": self.reference_text}
        if how: data["instruction"] = how
        files = {"ref_audio": ("reference.wav", self.reference, "audio/wav")}
        for attempt in range(21):
            request = self.client.build_request("POST", f"{self.url}/v1/audio/speech", data=data, files=files)
            response = await self.client.send(request, stream=True)
            if response.status_code != 409: break
            await response.aclose()
            if attempt < 20: await asyncio.sleep(.1)
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            if chunk: yield chunk[:len(chunk)//2*2]
        await response.aclose()


@dataclass(slots=True)
class SentenceJob:
    text: str
    how: str
    generation: int
    span: Span | None = None


@dataclass(slots=True)
class EndJob:
    generation: int
    span: Span | None = None


async def run(backend: TTSBackend, link: GameLink, speaking: Speaking, trace: Trace, jobs: asyncio.Queue[SentenceJob | EndJob]) -> None:
    audio_generation: int | None = None
    audio_until = time.monotonic()
    while True:
        job = await jobs.get()
        if isinstance(job, EndJob):
            if job.generation == speaking.generation: await link.send_json({"type":"audio_end"})
            speaking.end_line()
            if job.span:
                job.span.set(cut_off=job.generation != speaking.generation)
                job.span.finish()
            continue
        if job.generation != speaking.generation: continue
        await link.say(job.text)
        started = time.monotonic(); first: float | None = None; error: str | None = None; audio = bytearray()
        if job.span and "tts_request" not in job.span.data: job.span.mark("tts_request")
        try:
            async for chunk in backend.stream(job.text, job.how):
                if job.generation != speaking.generation: break
                if first is None:
                    first = (time.monotonic()-started)*1000
                    if job.span and "tts_first_audio" not in job.span.data: job.span.mark("tts_first_audio")
                    if audio_generation != job.generation:
                        if time.monotonic() < audio_until: await link.send_json({"type":"stop_audio"})
                        audio_generation = job.generation
                seconds = len(chunk)/2/backend.sample_rate
                audio_until = max(audio_until, time.monotonic())+seconds
                speaking.extend(seconds); await link.send_audio(chunk); audio.extend(chunk)
                if job.span and "first_audio_sent" not in job.span.data: job.span.mark("first_audio_sent")
                if job.span: job.span.mark("last_audio_sent")
        except Exception as exc: error = str(exc)
        trace.add("voice", {"text":job.text,"how":job.how,"first_audio_ms":round(first) if first is not None else None,"ms":round((time.monotonic()-started)*1000),"cut_off":job.generation != speaking.generation,"error":error})
        if trace.session_dir.joinpath("audio").exists() and audio:
            index = sum(1 for _ in trace.session_dir.joinpath("audio").glob(f"{job.span.data['turn_id'] if job.span else 'tts'}-tts-*.wav"))+1
            name = job.span.data["turn_id"] if job.span else "tts"
            trace.session_dir.joinpath("audio", f"{name}-tts-{index}.wav").write_bytes(wav_pcm(bytes(audio), backend.sample_rate))


def wav_pcm(pcm: bytes, rate: int) -> bytes:
    size = len(pcm)
    return b"RIFF"+(36+size).to_bytes(4,"little")+b"WAVEfmt "+(16).to_bytes(4,"little")+(1).to_bytes(2,"little")+(1).to_bytes(2,"little")+rate.to_bytes(4,"little")+(rate*2).to_bytes(4,"little")+(2).to_bytes(2,"little")+(16).to_bytes(2,"little")+b"data"+size.to_bytes(4,"little")+pcm


async def voice_design(url: str, description: str, text: str, out: Path, seed: int = 42) -> None:
    """Breeze reference-free design: text+instruction+cfg_scale+seed, no reference fields."""
    async with httpx.AsyncClient(timeout=180) as client:
        health = (await client.get(f"{url.rstrip('/')}/health")).json(); rate = int(health["sample_rate"])
        data = {"text":text,"instruction":description,"cfg_scale":"4","seed":str(seed)}
        async with client.stream("POST", f"{url.rstrip('/')}/v1/audio/speech", data=data) as response:
            response.raise_for_status(); pcm = b"".join([chunk async for chunk in response.aiter_bytes()])
    out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(wav_pcm(pcm, rate)); out.with_suffix(".txt").write_text(text.strip()+"\n")
