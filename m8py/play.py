"""Skill mode (docs/design/kevin-skill-loop.html): the runner steps Kevin's current skill on every
game state; the actor picks the next skill when something happens (a player line, a skill
ending, a game event) and on a heartbeat in combat; tickets ask the coach for new or fixed
skills. Library changes load between skills."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import deque
from typing import Any, Callable

import httpx

from .actor import Actor, Decision, parse
from .body import Body
from .config import Config
from .skills import Done, Failed, Library, Runner, Running
from .trace import Trace

HEARTBEAT = 3.0  # seconds between decisions while enemies are around, with nothing new
REVIEW = 600.0  # seconds of play between review tickets
RULES = (
    "You choose what Kevin, the player's Marine teammate in Halo, does next. Answer with ONE "
    "line and nothing else:\n"
    "  <skill> <args>                  start this skill now (args in order, or name=value)\n"
    "  keep                            the running skill still fits\n"
    "  nofit <order> | <skill> <args>  no skill does what the player asked; do the nearest one "
    "meanwhile\n"
    "Enemies are named kind#id (grunt#31). Protect the player; never shoot them.\n"
    "- Standing orders (hold fire, stay close, stay behind me) hold until the player changes "
    "them. A one-off order (flank him, go there, take that out) is over when its skill ends.\n"
    "- When a skill's description matches what the player asked, answer with that skill, even "
    "if it can't succeed right now (no enemies, no target): it will report why. nofit is only "
    "for something the player just asked, in their own words, that no skill's description "
    "matches; never for a skill that failed or for anything the player didn't say.\n"
    "- Don't start again a skill that just failed for the same reason; pick another or follow."
)


class Play:
    def __init__(
        self,
        cfg: Config,
        link: Any,
        trace: Trace,
        client: httpx.AsyncClient,
        orders: Callable[[], list[str]],
        fill: Callable[[str], str],
    ) -> None:
        assert cfg.actor
        self.cfg, self.link, self.trace = cfg.actor, link, trace
        self.orders, self.fill = orders, fill
        self.library = Library(cfg.actor.library)
        self.body = Body()
        self.runner = Runner(self.library, self.body, self._ended)
        self.actor = Actor(cfg.actor, client)
        self.reasons: list[str] = []
        self.wake = asyncio.Event()
        self.last: str = "nothing yet"
        self.last_decision = 0.0
        self.failures: dict[str, list[float]] = {}
        self.ticketed: set[str] = set()
        self.next_review = time.monotonic() + REVIEW
        self.decisions = 0
        self.retried = False
        self.story: deque[str] = deque(maxlen=80)  # recent decisions and skill ends, for tickets

    # ---------- the game's side

    def on_state(self, state: dict[str, Any]) -> None:
        if not isinstance(state.get("kevin"), dict):
            return
        self.body.update(state)
        if self.runner.current is None and self.library.changed():
            self.library.load()
            self.trace.add(
                "library", {"skills": sorted(self.library.skills), "errors": self.library.errors}
            )
        self.runner.tick()
        if self.body.outbox:
            outbox, self.body.outbox = self.body.outbox, []
            self.trace.add("body", {"sent": outbox})
            asyncio.get_running_loop().create_task(self._send(outbox))

    async def _send(self, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            await self.link.send_json(message)

    def trigger(self, reason: str) -> None:
        self.reasons.append(reason)
        self.wake.set()

    def reset(self) -> None:
        self.runner.stop()
        self.reasons.clear()
        self.last = "nothing yet"

    def doing(self) -> str:
        running = self.runner.current
        if running:
            return f"{running.display()} (for {time.monotonic() - running.started:.0f} s)"
        return self.last

    def _ended(self, running: Running, result: Done | Failed) -> None:
        verb = "done" if isinstance(result, Done) else "failed"
        self.last = f"{running.display()}: {verb}, {result.reason}"
        self.trace.add(
            "skill", {"skill": running.skill.name, "args": running.args, verb: result.reason}
        )
        print(f"[skill] {self.last}", flush=True)
        self.story.append(f"{time.strftime('%H:%M:%S')} {self.last}")
        if isinstance(result, Failed):
            now = time.monotonic()
            recent = [t for t in self.failures.get(running.skill.name, []) if now - t < 180] + [now]
            self.failures[running.skill.name] = recent
            if result.reason.startswith("error") or len(recent) >= 2:
                self.ticket(
                    "failure", skill=running.skill.name, args=running.args, reason=result.reason
                )
        self.trigger(f"{running.display()} {verb}: {result.reason}")

    # ---------- deciding

    def system(self) -> str:
        notes = self.cfg.library / "actor" / "prompt.md"
        tags = {"combat"} if self.body.enemies else {"calm"}
        catalog = "\n".join(f"  {s.line()}" for s in self.library.catalog(tags))
        extra = notes.read_text().strip() if notes.exists() else ""
        return f"{RULES}\n\nSkills:\n{catalog}\n\n{extra}".strip()

    def digest(self, reasons: list[str]) -> str:
        state, me, player = self.body.state, self.body.me, self.body.player
        enemies = [
            f"{e.get('kind')}#{e.get('id')} {e.get('distance_m', 0):.0f} m "
            f"{self.body.direction(e.get('pos'))}, "
            f"{'in sight' if e.get('in_sight') else 'out of sight'}, "
            f"health {100 * float(e.get('health', 1)):.0f}%"
            for e in sorted(self.body.enemies, key=lambda e: e.get("distance_m", 0))[:8]
        ]
        aim = player.get("aim") or {}
        return "\n".join(
            [
                self.fill(str(state.get("state", ""))),
                f"Kevin: health {100 * float(me.get('health', 1)):.0f}%, shields "
                f"{100 * float(me.get('shields', 1)):.0f}%. Player: health "
                f"{100 * float(player.get('health', 1)):.0f}%, aiming at "
                f"{aim.get('label', 'nothing')} {aim.get('distance_m', 0):.0f} m away.",
                f"Enemies: {'; '.join(enemies) or 'none'}.",
                f"Running: {self.doing()}.",
                f"Orders: {'; '.join(self.orders()) or 'none'}.",
                "Since the last decision: " + " / ".join(reasons),
            ]
        )

    async def run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self.wake.wait(), HEARTBEAT)
            except asyncio.TimeoutError:
                if not self.body.enemies or not self.body.state:
                    continue
                self.reasons.append("heartbeat")
            self.wake.clear()
            if not self.body.state:
                continue
            reasons, self.reasons = self.reasons, []
            try:
                await self.decide(reasons)
                self.retried = False
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}".strip(": ")
                self.trace.add("decision", {"reasons": reasons, "error": error})
                print(f"[actor] error: {error}", flush=True)
                # (a timeout or a 502 passes: what the player said is asked about once more)
                if not self.retried and any(r != "heartbeat" for r in reasons):
                    self.retried = True
                    self.reasons[:0] = [r for r in reasons if r != "heartbeat"]
                    self.wake.set()
            if time.monotonic() > self.next_review and self.decisions:
                self.next_review = time.monotonic() + REVIEW
                self.ticket("review", decisions=self.decisions)

    async def decide(self, reasons: list[str]) -> Decision:
        system, user = self.system(), self.digest(reasons)
        answer, ms, usage = await self.actor.ask(system, user)
        decision = parse(answer, self.library)
        asked = any(reason.startswith("the player said") for reason in reasons)
        if decision.kind != "keep" or reasons != ["heartbeat"]:
            self.story.append(f"{time.strftime('%H:%M:%S')} {' / '.join(reasons)} => {answer}")
        error = self.apply(decision, asked)
        retry = None
        if error:  # one more try, told why
            again = f'{user}\n\nYour answer "{answer}" could not run: {error}. Answer again.'
            retry, more, _ = await self.actor.ask(system, again)
            ms += more
            decision = parse(retry, self.library)
            self.story.append(f"  (could not run: {error}) => {retry}")
            error = self.apply(decision, asked)
            if error:
                self.story.append(f"  (could not run: {error})")
        self.decisions += 1
        self.last_decision = time.monotonic()
        self.trace.add(
            "decision",
            {
                "reasons": reasons,
                "digest": user,
                "answer": answer,
                "retry": retry,
                "kind": decision.kind,
                "skill": decision.skill,
                "args": decision.args,
                "error": error,
                "ms": ms,
                "usage": usage,
            },
        )
        print(f"[actor] {retry or answer} ({ms} ms) <- {' / '.join(reasons)[:120]}", flush=True)
        return decision

    def apply(self, decision: Decision, asked: bool = True) -> str | None:
        """Starts the decided skill. A nofit becomes a ticket only when the player just spoke:
        the actor also says nofit about failed skills and orders it made up."""
        if decision.kind == "keep":
            return None
        if decision.kind == "invalid":
            return decision.error
        fresh = decision.order and decision.order not in self.ticketed
        if decision.kind == "nofit" and decision.skill and decision.order:
            # (the actor also says nofit for an order its skill names but can't do now)
            phrases = re.findall(r'"([^"]+)"', self.library.skills[decision.skill].when)
            if any(phrase.lower() in decision.order.lower() for phrase in phrases):
                fresh = False
        if decision.kind == "nofit" and asked and fresh:
            self.ticketed.add(decision.order)
            self.ticket(
                "new_order", order=decision.order, meanwhile=decision.skill, args=decision.args
            )
        if decision.skill:
            return self.runner.start(decision.skill, decision.args)
        return None

    # ---------- the coach's tickets

    def ticket(self, kind: str, **about: Any) -> None:
        self.cfg.tickets.mkdir(parents=True, exist_ok=True)
        ident = f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}"
        ticket = {
            "id": ident,
            "kind": kind,
            **about,
            "level": self.body.state.get("level"),
            "state": self.digest([]) if self.body.state else "",
            "recent": list(self.story),
            "trace": str(self.trace.session_dir / "trace.jsonl"),
            "library_errors": self.library.errors,
        }
        (self.cfg.tickets / f"{ident}.json").write_text(json.dumps(ticket, indent=1))
        self.trace.add("ticket", ticket)
        print(f"[coach] ticket {ident}", flush=True)
