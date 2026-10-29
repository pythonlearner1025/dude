"""Asks the real actor (OpenRouter) what Kevin does for a set of player lines, with no game: the
skill library as it is, in the sample calm and combat situations of m8py.skilltest. A quick
check after changing the actor's rules or the library's `when` lines.

Usage: python tools/actor_probe.py <library> [--config configs/b650s-skills.toml]
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import httpx

from m8py.config import Config
from m8py.play import Play
from m8py.skilltest import situation
from m8py.trace import Trace

LINES = [
    "Push them back.",
    "Flank right.",
    "Clear the area.",
    "Get behind that rock.",
    "Get in front of me.",
    "Hold your fire.",
    "Cover me.",
    "What's your favorite color?",
    "Make them run away scared.",
]


class Link:
    async def send_json(self, message):
        pass


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--config", default="configs/b650s-skills.toml")
    args = parser.parse_args()
    cfg = Config.load(args.config)
    cfg.actor.library = args.library.resolve()
    cfg.actor.tickets = Path("/tmp/actor-probe-tickets")
    trace = Trace(Path("/tmp/actor-probe-logs"))
    trace.start()
    async with httpx.AsyncClient() as client:
        for kind in ("calm", "combat"):
            for line in LINES:
                play = Play(cfg, Link(), trace, client, lambda: [], lambda t: t)
                play.on_state(situation(kind)[0])
                decision = await play.decide([f'the player said "{line}"'])
                shown = decision.skill or ""
                if decision.args:
                    shown += " " + " ".join(f"{v}" for v in decision.args.values())
                print(f"{kind:6} {line:32} -> {decision.kind:5} {shown} {decision.order or ''}")
    await trace.close()


if __name__ == "__main__":
    asyncio.run(main())
