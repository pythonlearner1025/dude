"""Prints one session as a timeline: speech, Kev decisions, validator, orders, Reflect, vision.

Usage: python tools/timeline.py <logs/session>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def kev_answers(data: dict) -> dict:
    out = {}
    for call in data.get("calls", []):
        for question, answer in ((call.get("response") or {}).get("answers") or {}).items():
            if answer.get("choice"):
                probs = sorted((answer.get("probabilities") or {}).items(), key=lambda x: -x[1])
                top = ", ".join(f"{name} {p:.2f}" for name, p in probs[:3])
                out[question] = f"{answer['choice']} [{top}]"
            else:
                out[question] = round(answer.get("noul", 0), 2)
    return out


def main() -> None:
    session = Path(sys.argv[1])
    rows = [json.loads(line) for line in (session / "trace.jsonl").read_text().splitlines()]
    t0 = rows[0]["t"]
    for row in rows:
        kind, d = row["kind"], row["data"]
        at = f"{(row['t'] - t0) / 1000:7.1f} "
        if kind == "heard":
            print(f"{at}PLAYER: {d.get('text')}")
        elif kind == "event":
            print(f"{at}event{'*' if d.get('react') else ''}: {str(d.get('text'))[:150]}")
        elif kind == "kev":
            noise = "noise " if d.get("noise") else ""
            print(
                f"{at}kev: {d.get('action')} {d.get('option') or ''} speak={d.get('speak')} "
                f"{noise}cmd={d.get('is_command')} cd={d.get('cooldown')} {kev_answers(d)} "
                f"{d.get('ms')}ms"
            )
        elif kind == "llm":
            cut = " (CUT)" if d.get("cut_off") else ""
            error = f" ERR={d['error']}" if d.get("error") else ""
            print(f"{at}KEVIN: {d.get('line')}{cut}{error} [first {d.get('first_token_ms')}ms]")
        elif kind == "voice" and (d.get("cut_off") or d.get("error")):
            print(f"{at}  voice {'cut' if d.get('cut_off') else d.get('error')}: {d.get('text')!r}")
        elif kind == "validator":
            what = f"{d.get('action')} {d.get('option') or ''} {d.get('label') or ''}"
            print(f"{at}validator: {what} -> {d.get('status')}")
        elif kind == "orders":
            print(f"{at}ORDERS: {d.get('orders')} ({d.get('reason')})")
        elif kind == "reflect" and not d.get("interrupted"):
            print(f"{at}reflect {d.get('ms')}ms ({d.get('reason')}) {d.get('error') or ''}")
            print(f"{' ' * 10}{d.get('output', '')[:300]!r}")
        elif kind == "sight":
            print(f"{at}sight {d.get('kind')}: {d.get('seen')!r} err={d.get('error')}")


if __name__ == "__main__":
    main()
