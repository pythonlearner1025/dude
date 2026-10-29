from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
import time
from pathlib import Path

import httpx
import numpy as np
from aiohttp import web

from .brain import Brain, Event, Heard, Loaded, NewGame, Saved
from .config import Config
from .link import GameLink
from .listen import Listener, Transcriber, decode_wav, remote_mic_app, resample, run_local
from .site import create_app
from .speak import BreezeBackend, voice_design
from .speak import run as run_speech
from .speaking import Speaking
from .trace import Trace, generate_report, gpu_sampler


def health_url(endpoint: str) -> str:
    for suffix in ("/v1/systemone", "/v1/chat/completions", "/v1/audio/transcriptions"):
        if endpoint.endswith(suffix):
            return endpoint[: -len(suffix)] + "/health"
    return endpoint.rstrip("/") + "/health"


async def wait_health(name: str, url: str, client: httpx.AsyncClient) -> None:
    print(f"Waiting for {name} at {url} ...", flush=True)
    last = ""
    for _ in range(120):
        try:
            response = await client.get(url, timeout=2)
            if response.is_success:
                return
            last = f"HTTP {response.status_code}"
        except Exception as exc:
            last = str(exc)
        await asyncio.sleep(0.5)
    raise RuntimeError(f"{name} at {url} is not ready: {last}")


async def run(cfg: Config) -> Path:
    client = httpx.AsyncClient(timeout=60)
    await asyncio.gather(
        *([wait_health("Kev", health_url(cfg.kev.url), client)] if cfg.kev else []),
        wait_health("LLM", health_url(cfg.llm.url), client),
        wait_health("voice", cfg.mate.voice_server.rstrip("/") + "/health", client),
        wait_health("STT", health_url(cfg.stt.url), client),
    )
    trace = Trace(cfg.log.directory, save_audio=cfg.log.save_audio)
    trace.start()
    speaking = Speaking()
    inputs = asyncio.Queue()
    events = asyncio.Queue()
    hearing = asyncio.Queue()
    speech = asyncio.Queue()
    voice = await BreezeBackend.load(cfg, client)
    link = GameLink(
        {"type": "hello", "name": cfg.mate.name, "sample_rate": voice.sample_rate}, events, hearing
    )
    await link.start(cfg.game.port, cfg.game.bind)
    transcriber = Transcriber(cfg.stt.url, cfg.stt.model, client)
    brain = Brain(cfg, link, speech, speaking, trace, inputs, client)
    site_runner = web.AppRunner(
        create_app(trace, brain.system_file, brain.combat, brain.radio, link, inputs)
    )
    await site_runner.setup()
    await web.TCPSite(site_runner, cfg.site.bind, cfg.site.port).start()
    listener = Listener(
        cfg,
        transcriber,
        16000,
        lambda text, timing, turn_id: inputs.put(Heard(text, timing, turn_id)),
        trace,
    )
    print(f"[mic] VAD: {cfg.mic.vad}", flush=True)
    remote_runner = None
    tasks = [
        asyncio.create_task(brain.run()),
        asyncio.create_task(run_speech(voice, link, speaking, trace, speech)),
        asyncio.create_task(gpu_sampler(trace, cfg.log.gpu_interval)),
    ]

    joined = None

    async def join(link: str) -> None:
        """Starts Kevin's own game on the host's invite, with Open-P2P playing it."""
        nonlocal joined
        if not cfg.p2p or not cfg.p2p.launch or not link or link == joined:
            return
        joined = link
        print(f"[p2p] joining the host's invite as {cfg.mate.name}", flush=True)
        trace.add("invite", {"link": link})
        process = await asyncio.create_subprocess_exec(
            str(cfg.p2p.launch), link, stdin=asyncio.subprocess.DEVNULL
        )
        if await process.wait():
            print(f"[p2p] {cfg.p2p.launch} failed ({process.returncode})", flush=True)

    async def forward_events():
        while True:
            msg = await events.get()
            kind = msg.get("type")
            if kind == "invite":
                await join(str(msg.get("link", "")))
                continue
            if kind == "saved":
                item = Saved(str(msg.get("id", "")))
            elif kind == "loaded":
                item = Loaded(str(msg.get("id", "")))
            elif kind == "new_game":
                item = NewGame(str(msg.get("level", "")))
            elif kind == "direct":
                item = Event(
                    f"Game master: {msg.get('text', '')}",
                    True,
                    {"event_received_at": msg.get("_received_at", time.monotonic())},
                )
            else:
                item = Event(
                    str(msg.get("text", "")),
                    bool(msg.get("react", True)),
                    {"event_received_at": msg.get("_received_at", time.monotonic())},
                )
            await inputs.put(item)

    async def forward_hearing():
        while True:
            about, samples, received_at = await hearing.get()
            started = time.monotonic()
            rate = int(about.get("sample_rate", 16000))
            audio = resample(np.asarray(samples, np.float32), rate)
            text = await transcriber.transcribe(audio)
            stt_done_at = time.monotonic()
            if not text:
                continue
            await asyncio.sleep(max(0, len(samples) / rate - (time.monotonic() - started)))
            playback_wait_done_at = time.monotonic()
            radio = " over the radio" if about.get("radio") else ""
            await inputs.put(
                Event(
                    f'{about.get("speaker", "Someone")}{radio}: "{text}"',
                    bool(about.get("react", True)),
                    {
                        "event_received_at": received_at,
                        "stt_done_at": stt_done_at,
                        "playback_wait_done_at": playback_wait_done_at,
                    },
                )
            )

    tasks += [asyncio.create_task(forward_events()), asyncio.create_task(forward_hearing())]
    if cfg.mic.source == "remote":
        remote_runner = web.AppRunner(await remote_mic_app(listener, speaking, link, cfg))
        await remote_runner.setup()
        await web.TCPSite(remote_runner, cfg.remote_mic.bind, cfg.remote_mic.port).start()
        print(f"Remote mic: ws://{cfg.remote_mic.bind}:{cfg.remote_mic.port}/mic", flush=True)
    elif cfg.mic.source == "local":
        tasks.append(asyncio.create_task(run_local(listener, speaking, link)))
    elif cfg.mic.source != "none":
        raise ValueError(f"unknown mic source: {cfg.mic.source}")

    async def stdin_lines():
        while line := await asyncio.to_thread(sys.stdin.readline):
            if line.strip():
                await inputs.put(Heard(line.strip()))

    if not sys.stdin.closed:
        tasks.append(asyncio.create_task(stdin_lines()))
    ready = (
        f"Waiting for a game on {cfg.game.bind}:{cfg.game.port}\n"
        f"Brain page: http://{cfg.site.bind}:{cfg.site.port}\n"
        f"Ready! Talk to {cfg.mate.name} (or type a line here)."
    )
    print(
        ready,
        flush=True,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await link.close()
    await site_runner.cleanup()
    if remote_runner:
        await remote_runner.cleanup()
    await trace.close()
    await client.aclose()
    return trace.session_dir


async def transcribe_files(cfg: Config, paths: list[Path], simulate: bool = False) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        transcriber = Transcriber(cfg.stt.url, cfg.stt.model, client)
        await wait_health("STT", health_url(cfg.stt.url), client)
        for path in paths:
            samples, rate = decode_wav(path.read_bytes())
            samples = resample(samples, rate)
            if not simulate:
                print(f'{path}: "{await transcriber.transcribe(samples)}"')
                continue
            heard = []

            async def output(text, timing, turn_id):
                heard.append(text)

            listener = Listener(cfg, transcriber, 48000, output)
            audio = resample(samples, 16000, 48000)
            audio = np.concatenate((audio, np.zeros(96000, np.float32)))
            print(f"== {path}")
            for at in range(0, len(audio), 480):
                await listener.feed(audio[at : at + 480])
            for text in heard:
                print(f'   heard: "{text}"')


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="m8py")
    sub = p.add_subparsers(dest="command")
    runp = sub.add_parser("run")
    runp.add_argument("config", nargs="?", default="m8.toml")
    runp.add_argument("--transcribe", nargs="+", type=Path)
    runp.add_argument("--simulate-mic", nargs="+", type=Path)
    report = sub.add_parser("report")
    report.add_argument("session", type=Path)
    design = sub.add_parser("voice-design")
    design.add_argument("--description", required=True)
    design.add_argument("--text", required=True)
    design.add_argument("--out", required=True, type=Path)
    design.add_argument("--url", default="http://127.0.0.1:7860")
    design.add_argument("--seed", type=int, default=42)
    bench = sub.add_parser("bench")
    bench.add_argument("--scenario", required=True, type=Path)
    bench.add_argument("--config", required=True, type=Path)
    bench.add_argument("--mocks", action="store_true")
    bench.add_argument("--running", action="store_true")
    bench.add_argument("--speed", type=float, default=1.0)
    return p


def main() -> None:
    args = parser().parse_args()
    command = args.command or "run"
    if command == "report":
        print(generate_report(args.session))
        return
    if command == "voice-design":
        asyncio.run(voice_design(args.url, args.description, args.text, args.out, args.seed))
        return
    if command == "bench":
        from .bench import print_result, run_benchmark

        session, result = asyncio.run(
            run_benchmark(
                args.scenario,
                args.config,
                mocks=args.mocks,
                running=args.running,
                speed=args.speed,
            )
        )
        print_result(session, result)
        if not result["passed"]:
            raise SystemExit(1)
        return
    cfg = Config.load(getattr(args, "config", "m8.toml"))
    if args.transcribe or args.simulate_mic:
        asyncio.run(
            transcribe_files(cfg, args.transcribe or args.simulate_mic, bool(args.simulate_mic))
        )
    else:
        asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
