from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class Trace:
    """Non-blocking Rust-compatible trace plus per-turn span writer."""

    def __init__(self, logs: Path, session: str | None = None, save_audio: bool = False) -> None:
        self.session = session or str(now_ms() // 1000)
        self.session_dir = logs / self.session
        self.session_dir.mkdir(parents=True, exist_ok=True)
        (self.session_dir / "views").mkdir(exist_ok=True)
        if save_audio:
            (self.session_dir / "audio").mkdir(exist_ok=True)
        self.entries: list[dict[str, Any]] = []
        self.prompt = ""
        self.queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None
        self._spans: dict[str, Span] = {}

    def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self._writer())

    def set_prompt(self, prompt: str) -> None:
        self.prompt = prompt

    def add(self, kind: str, data: dict[str, Any]) -> None:
        entry = {"id": len(self.entries), "t": now_ms(), "kind": kind, "data": data}
        self.entries.append(entry)
        self.queue.put_nowait(("trace.jsonl", entry))

    def new_span(self, trigger: str, turn_id: str | None = None, **initial: Any) -> Span:
        turn_id = turn_id or f"{now_ms()}-{len(self._spans) + 1}"
        span = Span(self, turn_id, trigger, initial)
        self._spans[turn_id] = span
        return span

    async def _writer(self) -> None:
        handles: dict[str, Any] = {}
        try:
            while (item := await self.queue.get()) is not None:
                name, record = item
                handle = handles.get(name)
                if handle is None:
                    handle = (self.session_dir / name).open("a", encoding="utf-8")
                    handles[name] = handle
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
        finally:
            for handle in handles.values():
                handle.close()

    async def close(self) -> None:
        await self.queue.put(None)
        if self.task:
            await self.task
        generate_report(self.session_dir)


class Span:
    def __init__(self, trace: Trace, turn_id: str, trigger: str, initial: dict[str, Any]) -> None:
        self.trace, self.started = trace, time.monotonic()
        converted = {
            key.removesuffix("_at"): round((value - self.started) * 1000, 3)
            if key.endswith("_at") and isinstance(value, (int, float))
            else value
            for key, value in initial.items()
        }
        self.data: dict[str, Any] = {"turn_id": turn_id, "trigger": trigger, **converted}
        queued_at = converted.get("stt_done") if trigger == "heard" else None
        if queued_at is None and trigger in {"event", "quiet"}:
            queued_at = converted.get("playback_wait_done", converted.get("event_received"))
        if isinstance(queued_at, (int, float)):
            self.data["queue_wait_ms"] = -queued_at
        self._finished = False

    def mark(self, stage: str) -> None:
        self.data[stage] = round((time.monotonic() - self.started) * 1000, 3)

    def set(self, **values: Any) -> None:
        self.data.update(values)

    def set_error(self, stage: str, error: BaseException | str) -> None:
        self.data.setdefault("error", str(error))
        self.data.setdefault("error_stage", stage)

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if (
            self.data.get("trigger") == "heard"
            and "first_audio_sent" in self.data
            and "vad_speech_end" in self.data
        ):
            self.data["mouth_to_ear_ms"] = (
                self.data["first_audio_sent"] - self.data["vad_speech_end"]
            )
        if self.data.get("trigger") in {"event", "quiet"} and "first_audio_sent" in self.data:
            self.data["event_to_ear_ms"] = self.data["first_audio_sent"] - self.data.get(
                "event_received", 0
            )
        self.trace.queue.put_nowait(("spans.jsonl", self.data.copy()))


async def gpu_sampler(trace: Trace, interval: float = 2.0) -> None:
    if shutil.which("nvidia-smi") is None:
        return
    while True:
        try:
            gpu = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await gpu.communicate()
            apps = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            appout, _ = await apps.communicate()
            rows = [r.split(", ") for r in out.decode().strip().splitlines() if r]
            processes = [r.split(", ", 2) for r in appout.decode().strip().splitlines() if r]
            record = {
                "t": now_ms(),
                "gpus": [
                    {"memory_used_mb": int(r[0]), "utilization_percent": int(r[1])} for r in rows
                ],
                "processes": [
                    {"pid": int(r[0]), "name": r[1], "memory_used_mb": int(r[2])} for r in processes
                ],
            }
            trace.queue.put_nowait(("gpu.jsonl", record))
        except (OSError, ValueError):
            return
        await asyncio.sleep(interval)


def _percentile(values: list[float], p: float) -> float:
    if len(values) == 1:
        return values[0]
    values = sorted(values)
    at = (len(values) - 1) * p
    lo = int(at)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (at - lo)


def generate_report(session_dir: str | Path) -> Path:
    session_dir = Path(session_dir)
    spans = []
    path = session_dir / "spans.jsonl"
    if path.exists():
        spans = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    numeric: dict[str, list[float]] = {}
    ignored = {"turn_id", "prompt_tokens_kev", "prompt_tokens_llm"}
    for span in spans:
        for key, value in span.items():
            if (
                key not in ignored
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                numeric.setdefault(key, []).append(float(value))
    actions = Counter(str(s.get("action")) for s in spans if s.get("action"))
    errors = Counter(str(s.get("error_stage", "unknown")) for s in spans if s.get("error"))
    spoke = [bool(s.get("spoke")) for s in spans if "spoke" in s]
    lines = [
        f"# m8py session {session_dir.name}",
        "",
        f"Turns: {len(spans)}",
        "",
        "## Latencies",
        "",
        "| Stage | p50 ms | p90 ms | max ms |",
        "|---|---:|---:|---:|",
    ]
    for key, vals in sorted(numeric.items()):
        p50 = _percentile(vals, 0.5)
        p90 = _percentile(vals, 0.9)
        lines.append(f"| {key} | {p50:.1f} | {p90:.1f} | {max(vals):.1f} |")
    spoke_percent = 100 * sum(spoke) / len(spoke) if spoke else 0
    lines += [
        "",
        "## Outcomes",
        "",
        f"Actions: {dict(actions)}",
        f"Spoke: {sum(spoke)}/{len(spoke)} ({spoke_percent:.1f}%)",
        f"Cut-offs: {sum(bool(s.get('cut_off')) for s in spans)}",
        f"Errors: {sum(bool(s.get('error')) for s in spans)}",
        f"Errors by stage: {dict(errors)}",
        "",
    ]
    report = session_dir / "summary.md"
    report.write_text("\n".join(lines))
    return report
