"""Skill mode (docs/design/kevin-skill-loop.html): the runner steps Kevin's current skill on every
game state; the actor picks the next skill when something happens (a player line, a skill
ending, a game event) and on a heartbeat in combat. Library changes load between skills.

Nothing here talks to the coach: the trace is the whole record (Kevin's state once a second,
frames of the player's view, every decision, skill ending and command), and the coach reads it
on its own heartbeat (m8py/observe.py)."""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
from typing import Any, Callable

import httpx
from PIL import Image

from .actor import Actor, Decision, parse
from .body import Body
from .config import Config
from .skills import Done, Failed, Library, Runner, Running
from .trace import Trace

HEARTBEAT = 3.0  # seconds between decisions while enemies are around, with nothing new
RETRY_AFTER = 10.0  # seconds before a failed skill starts again, unless the player asks
STATE_EVERY = 1.0  # seconds between state lines in the trace
FRAME_EVERY = 10.0  # seconds between frames of the player's view, and after each player line
FRAME_WIDTH = 640
RULES = (
    "You choose what Kevin, the player's Marine teammate in Halo, does next. Answer with ONE "
    "line and nothing else:\n"
    "  <skill> <args>   start this skill now (args in order, or name=value)\n"
    "  keep             the running skill still fits\n"
    "Enemies are named kind#id (grunt#31). Protect the player; never shoot them.\n"
    "- Standing orders (hold fire, stay close, stay behind me) hold until the player changes "
    "them. A one-off order (flank him, go there, take that out) is over when its skill ends.\n"
    "- When a skill's description matches what the player asked, answer with that skill, even "
    "if it can't succeed right now (no enemies, no target): it will report why. When none "
    "does, answer with the nearest one.\n"
    "- Don't start again a skill that just failed for the same reason; pick another or follow."
)


def rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, list):
        return [rounded(v) for v in value]
    return value


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
        self.retried = False
        self.traced_state = 0.0
        self.last_frame = 0.0
        self.framing = False
        self.failed: dict[str, tuple[str, float]] = {}  # skill -> (why, when) of its last failure
        self.head = self.library.head()
        self.on_learned: Callable[[str], None] | None = None  # Kevin tells the player

    # ---------- the game's side

    def on_state(self, state: dict[str, Any]) -> None:
        if not isinstance(state.get("kevin"), dict):
            return
        self.body.update(state)
        if self.library.changed():
            self._reload()
        self.runner.tick()
        if self.body.outbox:
            outbox, self.body.outbox = self.body.outbox, []
            self.trace.add("body", {"sent": outbox})
            asyncio.get_running_loop().create_task(self._send(outbox))
        if time.monotonic() - self.traced_state >= STATE_EVERY:
            self.traced_state = time.monotonic()
            self._trace_state()

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.library.directory), *args], capture_output=True, text=True
        ).stdout.strip()

    def _reload(self) -> None:
        """Loads the coach's changes at once; the running skill restarts if its code changed."""
        self.library.load()
        running, restarted = self.runner.current, None
        if running:
            fresh = self.library.skills.get(running.skill.name)
            if fresh and fresh.code != running.skill.code:
                if self.runner.start(running.skill.name, running.args) is None:
                    restarted = running.skill.name
        head = self.library.head()
        self.trace.add(
            "library",
            {
                "head": head[:7],
                "skills": sorted(self.library.skills),
                "errors": self.library.errors,
                "restarted": restarted,
            },
        )
        if self.head and head and head != self.head:
            # (what changed for the player: commits to skills or the actor's prompt, not notes)
            subjects = self._git(
                "log", "--format=%s", f"{self.head}..{head}", "--", "skills/*.py", "actor/*.md"
            )
            said = [re.sub(r"\s*\([^()]*\)$", "", line) for line in subjects.splitlines()]
            if said and self.on_learned:
                self.on_learned("; ".join(said))
        self.head = head

    def _trace_state(self) -> None:
        me, player = self.body.me, self.body.player
        aim = player.get("aim") or {}
        nearest = sorted(self.body.enemies, key=lambda e: e.get("distance_m", 0))[:6]
        keys = ("id", "kind", "pos", "distance_m", "in_sight", "health")
        self.trace.add(
            "state",
            {
                "level": self.body.state.get("level"),
                "kevin": {
                    **{k: rounded(me.get(k)) for k in ("pos", "facing", "health", "shields")},
                    "activity": me.get("activity"),
                    "target": (me.get("target") or {}).get("label"),
                },
                "player": {
                    **{k: rounded(player.get(k)) for k in ("pos", "facing", "health", "shields")},
                    "aim": {k: rounded(aim.get(k)) for k in ("label", "distance_m", "pos")}
                    if aim
                    else None,
                },
                "enemies": [{k: rounded(e.get(k)) for k in keys} for e in nearest],
                "running": self.doing(),
            },
        )

    async def _send(self, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            await self.link.send_json(message)

    async def frame(self, why: str) -> None:
        """Saves what the player sees, small, for the coach."""
        if self.framing or not hasattr(self.link, "view"):
            return
        self.framing, self.last_frame = True, time.monotonic()
        try:
            view = await self.link.view(2.0)
            if view is None:
                return
            name = f"views/{int(time.time() * 1000)}.jpg"
            path = self.trace.session_dir / name

            def save() -> None:
                image = Image.frombytes("RGB", (view.width, view.height), bytes(view.rgb))
                image.thumbnail((FRAME_WIDTH, FRAME_WIDTH))
                path.parent.mkdir(exist_ok=True)
                image.save(path, quality=70)

            await asyncio.to_thread(save)
            self.trace.add("view", {"file": name, "why": why})
        finally:
            self.framing = False

    def trigger(self, reason: str) -> None:
        self.reasons.append(reason)
        self.wake.set()
        if reason.startswith("the player said") and self.body.state:
            asyncio.get_running_loop().create_task(self.frame("the player spoke"))

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
        if isinstance(result, Failed):
            self.failed[running.skill.name] = (result.reason, time.monotonic())
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
        asyncio.get_running_loop().create_task(self._frames())
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

    async def _frames(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            if self.body.state and time.monotonic() - self.last_frame >= FRAME_EVERY:
                await self.frame(f"every {FRAME_EVERY:.0f} s")

    async def decide(self, reasons: list[str]) -> Decision:
        system, user = self.system(), self.digest(reasons)
        answer, ms, usage = await self.actor.ask(system, user)
        decision = parse(answer, self.library)
        asked = any(reason.startswith("the player said") for reason in reasons)
        error = self.apply(decision, asked)
        retry = None
        if error:  # one more try, told why
            again = f'{user}\n\nYour answer "{answer}" could not run: {error}. Answer again.'
            retry, more, _ = await self.actor.ask(system, again)
            ms += more
            decision = parse(retry, self.library)
            error = self.apply(decision, asked)
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
        """Starts the decided skill; an error message if it can't. A skill that failed moments
        ago doesn't start again unless the player asks: the actor would loop on it."""
        if decision.kind == "keep":
            return None
        if decision.kind == "invalid":
            return decision.error
        why, when = self.failed.get(decision.skill or "", ("", -RETRY_AFTER))
        if not asked and time.monotonic() - when < RETRY_AFTER:
            ago = time.monotonic() - when
            return f"{decision.skill} failed {ago:.0f} s ago ({why}); pick something else"
        if decision.skill:
            return self.runner.start(decision.skill, decision.args)
        return None
