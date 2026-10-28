"""Checks Voice's prompt-cache reuse on the LLM server (docs/findings.md §10.2).

1. For consecutive Voice requests in a session, how much of each prompt the previous one shares.
2. Replays two consecutive Voice prompts on slot 0, with and without one Reflect request on
   slot 1 in between, and prints how many tokens the second prompt reused.

Usage: python tools/voice_cache_probe.py <logs/session> [--url http://127.0.0.1:8081]
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


def flat(messages: list[dict]) -> str:
    return "".join(f"<{m['role']}>{m['content']}" for m in messages)


def post(url: str, request: dict) -> dict:
    body = json.load(
        urllib.request.urlopen(
            urllib.request.Request(
                f"{url}/v1/chat/completions",
                data=json.dumps(request).encode(),
                headers={"Content-Type": "application/json"},
            ),
            timeout=120,
        )
    )
    return body.get("timings", {})


def voice(url: str, request: dict, label: str) -> None:
    timings = post(url, dict(request, stream=False, max_tokens=1, id_slot=0))
    print(
        f"  {label}: reused {timings.get('cache_n')} tokens, read {timings.get('prompt_n')} "
        f"({timings.get('prompt_ms', 0):.0f} ms)"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8081")
    args = parser.parse_args()
    rows = [json.loads(line) for line in (args.session / "trace.jsonl").open()]
    voices = [r["data"]["request"] for r in rows if r["kind"] == "llm"]
    shared = []
    for a, b in zip(voices, voices[1:]):
        fa, fb = flat(a["messages"]), flat(b["messages"])
        n = next((i for i, (x, y) in enumerate(zip(fa, fb)) if x != y), min(len(fa), len(fb)))
        shared.append(n / len(fb))
    shared.sort()
    print(
        f"consecutive Voice prompts share median {100 * shared[len(shared) // 2]:.0f}% of the "
        f"newer prompt ({len(shared)} pairs)"
    )
    reflect = next(r["data"]["request"] for r in rows if r["kind"] == "reflect")
    middle = len(voices) // 2
    print("no other request in between:")
    voice(args.url, voices[middle], "turn N")
    voice(args.url, voices[middle + 1], "turn N+1")
    print("one Reflect request on slot 1 in between:")
    voice(args.url, voices[middle + 2], "turn M")
    post(args.url, reflect)
    voice(args.url, voices[middle + 3], "turn M+1")


if __name__ == "__main__":
    main()
