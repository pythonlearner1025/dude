from __future__ import annotations

import asyncio
import json
import signal
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .config import Config
from .fakegame import FakeGame, check_invariants
from .trace import generate_report


async def _wait_site(
    url: str, timeout: float = 30, process: asyncio.subprocess.Process | None = None
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = ""
    async with aiohttp.ClientSession() as client:
        while time.monotonic() < deadline:
            if process and process.returncode is not None:
                raise RuntimeError(f"m8py exited during startup with status {process.returncode}")
            try:
                async with client.get(url.rstrip("/") + "/trace") as response:
                    if response.status == 200:
                        return await response.json()
                    last = f"HTTP {response.status}"
            except (aiohttp.ClientError, OSError) as exc:
                last = str(exc)
            await asyncio.sleep(0.1)
    raise RuntimeError(f"m8py site did not become ready at {url}: {last}")


async def _capture(process: asyncio.subprocess.Process, path: Path) -> None:
    assert process.stdout
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        while line := await process.stdout.readline():
            text = line.decode(errors="replace")
            handle.write(text)
            handle.flush()
            print(text, end="")


def _port(url: str) -> int:
    parsed = urlparse(url)
    if parsed.port:
        return parsed.port
    return 443 if parsed.scheme == "https" else 80


async def _start_mocks(cfg: Config) -> asyncio.subprocess.Process:
    command = [
        sys.executable,
        "-m",
        "m8py.mocks",
        "--kev-port",
        str(_port(cfg.kev.url)),
        "--llm-port",
        str(_port(cfg.llm.url)),
        "--tts-port",
        str(_port(cfg.mate.voice_server)),
        "--stt-port",
        str(_port(cfg.stt.url)),
    ]
    return await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (index - low)


def bench_data(session_dir: Path, violations: list[str], log_text: str = "") -> dict[str, Any]:
    spans = _read_jsonl(session_dir / "spans.jsonl")
    fake = _read_jsonl(session_dir / "fakegame.jsonl")
    metrics: dict[str, dict[str, float | int | None]] = {}
    definitions = {
        "mouth_to_ear_ms": lambda s: s.get("mouth_to_ear_ms"),
        "event_to_ear_ms": lambda s: s.get("event_to_ear_ms"),
        "stt_ms": lambda s: _difference(s, "stt_done", "vad_speech_end"),
        "kev_total_ms": lambda s: _difference(s, "kev_done", "kev_start"),
        "llm_first_token_ms": lambda s: _difference(s, "llm_first_token", "llm_request"),
        "tts_first_audio_ms": lambda s: _difference(s, "tts_first_audio", "tts_request"),
    }
    for name, getter in definitions.items():
        values = [float(value) for span in spans if (value := getter(span)) is not None]
        metrics[name] = {
            "p50": _percentile(values, 0.5),
            "p90": _percentile(values, 0.9),
            "max": max(values) if values else None,
            "n": len(values),
        }
    actions = Counter(str(s["action"]) for s in spans if s.get("action"))
    errors = Counter(str(s.get("error_stage", "unknown")) for s in spans if s.get("error"))
    spoken = [bool(s["spoke"]) for s in spans if "spoke" in s]
    log_errors = [
        line
        for line in log_text.splitlines()
        if "Traceback (most recent call last)" in line or "[brain] error:" in line
    ]
    if log_errors:
        violations.append(f"m8py log contains {len(log_errors)} exception marker(s)")
    lines = [
        {
            "text": entry.get("message", {}).get("text", ""),
            "elapsed": entry.get("elapsed"),
        }
        for entry in fake
        if entry.get("kind") == "recv" and entry.get("message", {}).get("type") == "say"
    ]
    return {
        "session_dir": str(session_dir.resolve()),
        "metrics": metrics,
        "turns": len(spans),
        "actions": dict(actions),
        "spoke": {"yes": sum(spoken), "no": len(spoken) - sum(spoken)},
        "cut_offs": sum(bool(s.get("cut_off")) for s in spans),
        "errors_by_stage": dict(errors),
        "mate_lines": lines,
        "invariant_violations": violations,
        "passed": not violations,
    }


def _difference(span: dict[str, Any], end: str, start: str) -> float | None:
    if isinstance(span.get(end), (int, float)) and isinstance(span.get(start), (int, float)):
        return float(span[end]) - float(span[start])
    return None


async def run_benchmark(
    scenario: str | Path,
    config: str | Path,
    *,
    mocks: bool = False,
    running: bool = False,
    speed: float = 1.0,
) -> tuple[Path, dict[str, Any]]:
    cfg = Config.load(config)
    site_url = f"http://{cfg.site.bind}:{cfg.site.port}"
    mic_host = "127.0.0.1" if cfg.remote_mic.bind in {"0.0.0.0", "::"} else cfg.remote_mic.bind
    mic_url = f"ws://{mic_host}:{cfg.remote_mic.port}/mic"
    processes: list[asyncio.subprocess.Process] = []
    captures: list[asyncio.Task[None]] = []
    mock_log = cfg.log.directory / "bench-mocks.log"
    startup_log = cfg.log.directory / f"bench-m8py-{time.time_ns()}.log"
    try:
        if mocks:
            mock = await _start_mocks(cfg)
            processes.append(mock)
            captures.append(asyncio.create_task(_capture(mock, mock_log)))
        if not running:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "m8py",
                "run",
                str(Path(config).resolve()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            processes.append(process)
            captures.append(asyncio.create_task(_capture(process, startup_log)))
        live = await _wait_site(site_url, timeout=60, process=None if running else process)
        session_dir = cfg.log.directory / str(live["session"])
        m8_log = session_dir / "m8py.log"
        if not running:
            startup_log.replace(m8_log)
        fake = FakeGame(
            scenario,
            session_dir,
            host="127.0.0.1" if cfg.game.bind in {"0.0.0.0", "::"} else cfg.game.bind,
            port=cfg.game.port,
            site_url=site_url,
            mic_url=mic_url,
            speed=speed,
        )
        result = await fake.run()
    finally:
        for process in reversed(processes):
            if process.returncode is None:
                process.send_signal(signal.SIGTERM)
        for process in reversed(processes):
            try:
                await asyncio.wait_for(process.wait(), 15)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        await asyncio.gather(*captures, return_exceptions=True)
    generate_report(session_dir)
    violations = [*result.violations, *check_invariants(session_dir)]
    violations = list(dict.fromkeys(violations))
    log_text = m8_log.read_text() if m8_log.exists() else ""
    data = bench_data(session_dir, violations, log_text)
    (session_dir / "bench.json").write_text(json.dumps(data, indent=2) + "\n")
    report = generate_report(session_dir)
    with report.open("a", encoding="utf-8") as handle:
        handle.write("\n## Protocol invariants\n\n")
        if data["invariant_violations"]:
            for violation in data["invariant_violations"]:
                handle.write(f"- {violation}\n")
        else:
            handle.write("All protocol invariants passed.\n")
    return session_dir, data


def print_result(session_dir: Path, data: dict[str, Any]) -> None:
    print((session_dir / "summary.md").read_text())
    print(f"Benchmark JSON: {session_dir / 'bench.json'}")
