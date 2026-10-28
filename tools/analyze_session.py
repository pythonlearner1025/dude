"""Summarises an m8py session directory: turns, speech, actions, latency, VRAM, transcript.

Usage: python tools/analyze_session.py <logs/session> [--transcript out.md]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter
from pathlib import Path


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def pct(values: list[float], p: float) -> float:
    values = sorted(values)
    if not values:
        return float("nan")
    at = (len(values) - 1) * p
    lo = int(at)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (at - lo)


def row(name: str, values: list[float]) -> str:
    if not values:
        return f"| {name} | - | - | - | 0 |"
    return (
        f"| {name} | {pct(values, 0.5):.0f} | {pct(values, 0.9):.0f} | {max(values):.0f} "
        f"| {len(values)} |"
    )


def stage(span: dict, end: str, start: str) -> float | None:
    if isinstance(span.get(end), (int, float)) and isinstance(span.get(start), (int, float)):
        return span[end] - span[start]
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session", type=Path)
    parser.add_argument("--transcript", type=Path)
    args = parser.parse_args()
    trace = load(args.session / "trace.jsonl")
    spans = load(args.session / "spans.jsonl")
    gpu = load(args.session / "gpu.jsonl")

    t0, t1 = trace[0]["t"], trace[-1]["t"]
    heard = [e for e in trace if e["kind"] == "heard"]
    llm = [e for e in trace if e["kind"] == "llm"]
    kev = [e for e in trace if e["kind"] == "kev"]
    sight = [e for e in trace if e["kind"] == "sight"]
    voice = [e for e in trace if e["kind"] == "voice"]
    words = [len(e["data"].get("line", "").split()) for e in llm if e["data"].get("line")]
    triggers = Counter(span.get("trigger") for span in spans)
    event_spans = [s for s in spans if s.get("trigger") in ("event", "quiet")]
    spoke_events = sum(bool(s.get("spoke")) for s in event_spans)
    actions = Counter(e["data"].get("action") for e in kev)
    cooldown = sum(bool(e["data"].get("cooldown")) for e in kev)
    errors = Counter(s.get("error_stage") for s in spans if s.get("error"))
    cut = sum(bool(e["data"].get("cut_off")) for e in llm)
    notes = [d for e in llm for d in e["data"].get("directions", [])]
    long_notes = [n for n in notes if len(n.split()) > 6]
    openers = Counter(
        re.sub(r"\W+", " ", e["data"]["line"]).strip().split(" ")[0].lower()
        for e in llm
        if e["data"].get("line")
    )

    print(f"# Session {args.session.name}\n")
    print(
        f"- Span: {(t1 - t0) / 60000:.1f} min, {len(trace)} trace entries, {len(spans)} turns "
        f"({dict(triggers)})"
    )
    print(
        f"- Player lines heard: {len(heard)}; mate lines: {len(llm)} "
        f"({cut} cut off by barge-in or a newer turn); TTS sentences: {len(voice)}"
    )
    if words:
        print(
            f"- Words per mate line: median {statistics.median(words):.0f}, "
            f"mean {statistics.mean(words):.0f}, max {max(words)}"
        )
    if event_spans:
        print(
            f"- Game-event turns that spoke: {spoke_events}/{len(event_spans)} "
            f"({100 * spoke_events / len(event_spans):.0f}%); Kev decisions in cooldown: "
            f"{cooldown}/{len(kev)}"
        )
    print(f"- Actions chosen: {dict(actions.most_common())}")
    print(
        f"- Vision calls: {len(sight)}; voice directions: {len(notes)}, of which "
        f"{len(long_notes)} longer than 6 words (stage actions, not voice directions)"
    )
    print(f"- Most common first words of mate lines: {openers.most_common(5)}")
    print(f"- Errors by stage: {dict(errors) or 'none'}")
    if gpu:
        used = [g["gpus"][0]["memory_used_mb"] for g in gpu if g.get("gpus")]
        print(f"- GPU memory used: min {min(used)} MiB, max {max(used)} MiB")

    print("\n| Latency (ms) | p50 | p90 | max | n |\n|---|---:|---:|---:|---:|")
    print(
        row(
            "player speech end → first mate audio",
            [s["mouth_to_ear_ms"] for s in spans if "mouth_to_ear_ms" in s],
        )
    )
    print(
        row(
            "game event → first mate audio",
            [s["event_to_ear_ms"] for s in spans if "event_to_ear_ms" in s],
        )
    )
    print(row("queue wait", [s["queue_wait_ms"] for s in spans if "queue_wait_ms" in s]))
    print(
        row("STT", [v for s in spans if (v := stage(s, "stt_done", "vad_speech_end")) is not None])
    )
    print(
        row(
            "Kev decision chain",
            [v for s in spans if (v := stage(s, "kev_done", "kev_start")) is not None],
        )
    )
    print(
        row(
            "LLM first token",
            [v for s in spans if (v := stage(s, "llm_first_token", "llm_request")) is not None],
        )
    )
    print(
        row(
            "LLM first sentence",
            [v for s in spans if (v := stage(s, "first_sentence", "llm_request")) is not None],
        )
    )
    print(
        row(
            "TTS first audio",
            [v for s in spans if (v := stage(s, "tts_first_audio", "tts_request")) is not None],
        )
    )
    print(row("vision call", [e["data"]["ms"] for e in sight if "ms" in e["data"]]))
    print(
        row(
            "mate speech per reply (turn start → last audio)",
            [s["last_audio_sent"] for s in spans if "last_audio_sent" in s],
        )
    )

    if args.transcript:
        out = ["# Transcript\n"]
        for entry in trace:
            minute = (entry["t"] - t0) / 60000
            data = entry["data"]
            if entry["kind"] == "heard":
                out.append(f"- `{minute:5.1f}` **player:** {data.get('text')}")
            elif entry["kind"] == "event" and data.get("react"):
                out.append(f"- `{minute:5.1f}` event: {data.get('text')}")
            elif entry["kind"] == "kev" and data.get("action") not in (None, "nothing"):
                out.append(
                    f"- `{minute:5.1f}` *does:* {data.get('action')} {data.get('option') or ''}"
                )
            elif entry["kind"] == "llm":
                cut_note = " *(cut off)*" if data.get("cut_off") else ""
                out.append(f"- `{minute:5.1f}` **mate:** {data.get('line')}{cut_note}")
        args.transcript.write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
