from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .config import Config
from .link import GameLink
from .picture import base64, mark, png
from .play import Play
from .speak import EndJob, SentenceJob
from .speaking import Speaking
from .text import Notes, PieceKind, SentenceSplitter, clean, delivery_note, is_noise
from .trace import Span, Trace, now_ms
from .validator import ActionStatus, Validator

FEED_TOKENS, FEED_FOLDED_TO, FEED_MAX_TOKENS = 16_000, 12_000, 20_000
QUIET, QUIET_EVENT, KEV_FEED_LINES, SAVES = 45.0, "It's been quiet for a while.", 20, 50
REFLECT_INTERVAL, REFLECT_LOG_TOKENS, REFLECT_MAX_TOKENS = 15.0, 7_000, 768
REFLECT_THINK_TOKENS = 256  # unbudgeted thinking ran 1-2k tokens (12-27 s) and often never answered
EARLY_INSTRUCTION = re.compile(r'\s*\{\s*"instruction"\s*:\s*"((?:[^"\\]|\\.)*)"')


@dataclass(slots=True)
class Heard:
    text: str
    timing: dict[str, float] = field(default_factory=dict)
    turn_id: str | None = None


@dataclass(slots=True)
class Event:
    text: str
    react: bool = True
    timing: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class Learned:
    """The coach changed Kevin's skills; Kevin may tell the player what he does differently."""

    what: str


@dataclass(slots=True)
class Saved:
    ident: str


@dataclass(slots=True)
class Loaded:
    ident: str


@dataclass(slots=True)
class NewGame:
    level: str


@dataclass(slots=True)
class Summary:
    memory_generation: int
    folded: int
    text: str


Input = Heard | Event | Learned | Saved | Loaded | NewGame | Summary


def joint_options(
    name: str, actions: list[dict[str, Any]], fill: Any = lambda value: value
) -> tuple[dict[str, str], dict[str, tuple[str, str | None]]]:
    criteria = {"nothing": f"{name} carries on as he is"}
    choices: dict[str, tuple[str, str | None]] = {"nothing": ("nothing", None)}
    for action in actions:
        action_name = str(action.get("name", ""))
        description = fill(str(action.get("description", "")))
        targets = action.get("options") or {}
        if targets and len(targets) <= 8:
            for option, label in targets.items():
                key = f"{action_name}: {option}"
                criteria[key] = f"{name} {description}: {label}"
                choices[key] = (action_name, str(option))
            continue
        criteria[action_name] = f"{name} {description}"
        choices[action_name] = (action_name, None)
    return criteria, choices


@dataclass(slots=True)
class Memory:
    summary: str = ""
    feed: list[str] = field(default_factory=list)
    orders: list[str] = field(default_factory=list)
    remember: list[str] = field(default_factory=list)


class PromptFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.text = path.read_text() if path.exists() else ""

    def get(self) -> str:
        return self.text

    def set(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text)
        self.text = text


class Brain:
    def __init__(
        self,
        cfg: Config,
        link: GameLink,
        speech: asyncio.Queue[SentenceJob | EndJob],
        speaking: Speaking,
        trace: Trace,
        inputs: asyncio.Queue[Input],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.cfg, self.link, self.speech, self.speaking, self.trace, self.inputs = (
            cfg,
            link,
            speech,
            speaking,
            trace,
            inputs,
        )
        self.client = client or httpx.AsyncClient(timeout=60)
        p = cfg.persona_dir
        self.system_file = PromptFile(p / "system_prompt.txt")
        self.combat = PromptFile(p / "combat_prompt.txt")
        self.radio = PromptFile(p / "radio_prompt.txt")
        if not self.system_file.get().strip():
            raise ValueError(f"no system prompt in {p}")
        self.memory = Memory()
        self.memory_generation = 0
        self.summarizing = False
        self.waiting: Input | None = None
        try:
            self.saves = [(x[0], Memory(**x[1])) for x in json.loads(self.saves_path.read_text())]
        except (OSError, ValueError, TypeError):
            self.saves = []
        self._last_input = time.monotonic()
        self.reflect_log: list[str] = []
        self.reflect_task: asyncio.Task[None] | None = None
        self.reflect_pending = False
        self._last_reflect = time.monotonic()
        # With Kev, Reflect thinks for seconds and yields Gemma to Voice. Driving Open-P2P it
        # answers in about a second without thinking, beside Voice.
        self.reflect_thinks = cfg.kev is not None
        self.instruction = ""
        self.learned = ""  # what the coach just changed, until Kevin has said it
        if cfg.p2p:
            self.set_instruction("", force=True)
        self.validator = Validator(
            self.link.send_json, self._validator_changed, self._validator_failed
        )
        self.play = (
            Play(cfg, link, trace, self.client, lambda: self.memory.orders, self.fill)
            if cfg.actor
            else None
        )
        if self.play:
            self.play.on_learned = lambda what: self.inputs.put_nowait(Learned(what))
        if hasattr(self.link, "add_state_observer"):
            self.link.add_state_observer(self._on_state)

    @property
    def saves_path(self) -> Path:
        return self.cfg.base_dir / "saves.json"

    def state(self) -> dict[str, Any]:
        return self.link.state or {}

    def player(self) -> str:
        try:
            value = (self.cfg.base_dir / "player_name.txt").read_text().strip()
            if value:
                return value
        except OSError:
            pass
        return str(self.state().get("player_name") or "the player")

    def fill(self, text: str) -> str:
        return text.replace("{player}", self.player()).replace(
            "{game}", str(self.state().get("game", "a game"))
        )

    def context(self) -> list[str]:
        out = []
        level = self.state().get("level")
        if isinstance(level, str):
            path = self.cfg.persona_dir / "levels" / f"{level}.txt"
            if path.exists():
                out.append(self.fill(path.read_text().strip()))
        if self.memory.summary:
            out.append(f"What {self.cfg.mate.name} remembers: {self.memory.summary}")
        return out

    def orders_text(self) -> str:
        return "Orders:\n" + ("\n".join(f"- {x}" for x in self.memory.orders) or "- none")

    def remembers_text(self) -> str:
        return "Kevin remembers:\n" + (
            "\n".join(f"- {x}" for x in self.memory.remember) or "- nothing"
        )

    def doing_text(self) -> str:
        if self.play:
            return f"Kevin's current action: {self.play.doing()}"
        if self.cfg.p2p:
            return f"Kevin's current action: {self.instruction or 'playing on his own'}"
        current = self.validator.current
        if not current:
            return "Kevin's current action: nothing (done)"
        return f"Kevin's current action: {current.display()} ({current.status})"

    def right_now(self) -> str:
        return f"Right now: {self.fill(str(self.state().get('state', 'unknown')))}"

    def system(self) -> str:
        return self.fill(self.system_file.get().strip())

    def voice_system(self) -> str:
        return (
            self.system()
            + "\n\nRuntime rule: reply only with the words Kevin says out loud, in first person. "
            "Never narrate or describe his actions. His current action is listed below; if he "
            "mentions what he is doing, it must match it."
        )

    def situation(self) -> str:
        parts = []
        state = self.state()
        for key, prompt in (("in_combat", self.combat), ("on_radio", self.radio)):
            if state.get(key) and prompt.get().strip():
                parts.append(self.fill(prompt.get().strip()))
        parts.append(self.right_now())
        return "\n".join(parts)

    def newest(self) -> int:
        own = f"{self.cfg.mate.name}: "
        return next(
            (
                i + 1
                for i in range(len(self.memory.feed) - 1, -1, -1)
                if self.memory.feed[i].startswith(own)
            ),
            0,
        )

    def prompt(self) -> str:
        start = max(0, len(self.memory.feed) - KEV_FEED_LINES)
        newest = max(self.newest(), start)
        parts = [self.system(), *self.context(), self.orders_text(), self.remembers_text()]
        if newest > start:
            parts.append("\n".join(self.memory.feed[start:newest]))
        parts.append(self.situation())
        if newest < len(self.memory.feed):
            parts.append("\n".join(self.memory.feed[newest:]))
        return "\n\n".join(parts)

    def messages(self) -> list[dict[str, str]]:
        turns: list[list[str]] = [["system", self.voice_system()]]

        def add(role: str, text: str) -> None:
            if turns[-1][0] == role:
                turns[-1][1] += "\n" + text
            else:
                turns.append([role, text])

        context = "\n\n".join(self.context())
        if context:
            add("user", context)
        own = f"{self.cfg.mate.name}: "
        newest = self.newest()
        for line in self.memory.feed[:newest]:
            add("assistant", line[len(own) :]) if line.startswith(own) else add("user", line)
        volatile = [
            self.orders_text(),
            self.remembers_text(),
            self.doing_text(),
            self.situation(),
            *self.memory.feed[newest:],
        ]
        if self.learned:
            volatile.append(
                f"(In this line, also tell {self.player()} in a few words, your own way, what "
                f"you've just changed about how you fight beside them: {self.learned})"
            )
        turns.append(["user", "\n\n".join(volatile)])
        self.trace.set_prompt("\n\n".join(f"[{r}]\n{t}" for r, t in turns))
        return [{"role": r, "content": t} for r, t in turns]

    async def run(self) -> None:
        if self.play:
            self.play_task = asyncio.create_task(self.play.run())
        while True:
            quiet = False
            try:
                item = self.waiting or await asyncio.wait_for(self.inputs.get(), 1)
                self.waiting = None
            except asyncio.TimeoutError:
                state = self.state()
                if self.speaking.is_speaking() or not state or state.get("in_combat"):
                    self._last_input = time.monotonic()
                if time.monotonic() - self._last_input < QUIET:
                    continue
                quiet = True
                item = Event(QUIET_EVENT, True)
            if not isinstance(item, Summary):
                self._last_input = time.monotonic()
            try:
                if isinstance(item, Heard):
                    await self.on_heard(item)
                elif isinstance(item, Event):
                    events = [item]
                    while not self.inputs.empty():
                        more = self.inputs.get_nowait()
                        if isinstance(more, Event):
                            events.append(more)
                        else:
                            self.waiting = more
                            break
                    await self.on_events(events, quiet)
                elif isinstance(item, Learned):
                    # Kevin's next line carries it: now, unless he just spoke
                    self.learned = item.what
                    self.trace.add("event", {"text": f"(the coach changed Kevin: {item.what})"})
                    await self.respond(False, self.trace.new_span("learned"), quiet=True)
                elif isinstance(item, Saved):
                    await self.on_saved(item.ident)
                elif isinstance(item, Loaded):
                    await self.on_loaded(item.ident)
                elif isinstance(item, NewGame):
                    await self.on_new_game(item.level)
                else:
                    self.on_summary(item)
            except Exception as exc:
                print(f"[brain] error: {exc}")
            self.fold_over(FEED_TOKENS if quiet else FEED_MAX_TOKENS)
            self._reflect_heartbeat()

    async def on_heard(self, item: Heard) -> None:
        span = self.trace.new_span("heard", item.turn_id, **item.timing)
        await self.link.send_json({"type": "heard", "text": item.text})
        self.memory.feed.append(f"{self.player()}: {item.text}")
        self._reflect_log(f"{self.player()}: {item.text}")
        self.trace.add("heard", {"text": item.text})
        # Spoken lines only: typed lines have no turn id and often no punctuation.
        noise = item.turn_id is not None and is_noise(item.text)
        if self.play and not noise:
            self.play.trigger(f'the player said "{item.text}"')
        await self.respond(True, span, noise=noise)

    async def on_events(self, events: list[Event], quiet: bool = False) -> None:
        span = self.trace.new_span("quiet" if quiet else "event", **events[0].timing)
        for event in events:
            text = self.fill(event.text)
            self.memory.feed.append(text)
            self._reflect_log(text)
            self.validator.on_event(text)
            if self.play:
                self.play.trigger(text)
            self.trace.add("event", {"text": text, "react": event.react, "state": self.state()})
        if any(e.react for e in events):
            await self.respond(False, span, quiet=quiet)
        else:
            span.set(spoke=False)
            span.finish()

    async def respond(
        self, to_player: bool, span: Span, noise: bool = False, quiet: bool = False
    ) -> None:
        speech_finishes = False
        try:
            q = self.speaking.quiet_from()
            cooldown = not to_player and (
                q is None or time.monotonic() < q + self.link.speech_cooldown
            )
            if self.cfg.kev:
                span.mark("kev_start")
                speak = await self.decide(to_player, cooldown, span, noise)
                span.mark("kev_done")
            else:
                # Nothing judges game events without Kev: answer the player, break silences.
                speak = (to_player and not noise) or (quiet and not cooldown)
                if to_player and not noise:
                    self._request_reflect("the player spoke")
                self.trace.add("decide", {"speak": speak, "noise": noise, "cooldown": cooldown})
            span.set(spoke=speak)
            if speak:
                if self.speaking.is_speaking():
                    self.speaking.interrupt()
                speech_finishes = await self.say(span)
        finally:
            if not speech_finishes:
                span.finish()

    def _on_state(self, state: dict[str, Any]) -> None:
        if self.play:
            self.play.on_state(state)
        self.validator.update(state)
        self._reflect_heartbeat()

    def _validator_changed(self, current: ActionStatus) -> None:
        data = {
            "action": current.action,
            "option": current.option,
            "label": current.label,
            "status": current.status,
        }
        self.trace.add("validator", data)
        self._reflect_log(f"Kevin action: {current.display()} — {current.status}.")

    def _validator_failed(self, current: ActionStatus) -> None:
        self._request_reflect(f"{current.display()} failed or made no progress")

    def _reflect_log(self, line: str) -> None:
        self.reflect_log.append(line)
        if self.feed_tokens(self.reflect_log) > REFLECT_LOG_TOKENS:
            self.reflect_log = self.reflect_log[len(self.reflect_log) // 2 :]

    def _reflect_heartbeat(self) -> None:
        busy = self.memory.orders or self.instruction
        if busy and time.monotonic() - self._last_reflect >= REFLECT_INTERVAL:
            self._request_reflect("orders heartbeat")

    def _request_reflect(self, reason: str) -> None:
        if self.reflect_task and not self.reflect_task.done():
            self.reflect_pending = True
            return
        self.reflect_task = asyncio.create_task(self._reflect(reason))

    async def _reflect(self, reason: str) -> None:
        self._last_reflect = time.monotonic()
        started = time.monotonic()
        system = (
            "Maintain Kevin's durable orders and relationship memory. Orders are the standing "
            "instructions the player has given Kevin that still apply: keep the player's "
            "conditions and wording, add new ones, and drop ones the player cancelled or that "
            "are finished. Ignore talk that is not addressed to Kevin. Remember holds only "
            "lasting facts about the player or the relationship (names, preferences, promises); "
            "never positions, health, ammo, targets or anything about the current moment, and "
            "never what Kevin did. "
        )
        lists = {"type": "array", "items": {"type": "string"}}
        properties: dict[str, Any] = {"orders": lists, "remember": lists}
        # The log comes before what changes between runs, so the server can reuse its prefix.
        state = (
            f"Summary:\n{self.memory.summary or 'none'}\n\nAppend-only log (newest last):\n"
            + ("\n".join(self.reflect_log) or "none")
            + f"\n\n{self.orders_text()}\n\n{self.remembers_text()}"
        )
        if self.cfg.p2p:
            system += (
                "Instruction is what Kevin's body does right now to carry out his orders and "
                "the player's newest request: one short plain command such as \"follow the "
                'player", "move forward", "shoot the enemies" or "take cover behind the '
                'rocks". Keep it unchanged while it still applies; leave it empty when there '
                "is nothing to do but play along. Output JSON only with exactly: instruction, "
                "then orders and remember, each the full replacement list of short strings."
            )
            # First, so Open-P2P gets it while the lists are still being written.
            properties = {"instruction": {"type": "string", "maxLength": 120}, **properties}
            state += f"\n\nInstruction now: {self.instruction or 'none'}"
        else:
            system += (
                "Never send or propose a game action. Output JSON only with exactly: orders "
                "and remember, each the full replacement list of short strings."
            )
        request: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"{state}\n\nCurrent state:\n{self.right_now()}\n\nDecide.",
                },
            ],
            "temperature": 0.3,
            "stream": True,
            "max_tokens": REFLECT_MAX_TOKENS,
            "id_slot": 1,
            "chat_template_kwargs": {"enable_thinking": self.reflect_thinks},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "reflection",
                    "schema": {
                        "type": "object",
                        "properties": properties,
                        "required": list(properties),
                    },
                },
            },
        }
        if self.reflect_thinks:
            request["thinking_budget_tokens"] = REFLECT_THINK_TOKENS
        output = ""
        error = None
        interrupted = False
        try:
            async with self.client.stream("POST", self.cfg.llm.url, json=request) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: ") or line[6:].strip() == "[DONE]":
                        continue
                    choices = json.loads(line[6:]).get("choices") or []
                    output += (choices[0].get("delta", {}).get("content") or "") if choices else ""
                    if self.cfg.p2p and (early := EARLY_INSTRUCTION.match(output)):
                        self.set_instruction(json.loads(f'"{early[1]}"').strip())
            result = json.loads(output)
            orders = [str(x).strip() for x in result.get("orders", []) if str(x).strip()]
            remember = [str(x).strip() for x in result.get("remember", []) if str(x).strip()]
            if orders != self.memory.orders:
                self.memory.orders = orders
                self.trace.add("orders", {"orders": orders, "reason": reason})
            self.memory.remember = remember
            if self.cfg.p2p:
                self.set_instruction(str(result.get("instruction", "")).strip())
        except asyncio.CancelledError:
            interrupted = True
            raise
        except Exception as exc:
            error = str(exc)
        finally:
            self.trace.add(
                "reflect",
                {
                    "request": request,
                    "output": output,
                    "ms": round((time.monotonic() - started) * 1000),
                    "reason": reason,
                    "interrupted": interrupted,
                    "error": error,
                },
            )
            if self.reflect_task is asyncio.current_task():
                self.reflect_task = None
            if not interrupted and self.reflect_pending:
                self.reflect_pending = False
                asyncio.get_running_loop().call_soon(
                    self._request_reflect, "triggered while reflection was running"
                )

    def set_instruction(self, text: str, force: bool = False) -> None:
        """Hands Open-P2P its instruction: tools/p2p/server.py watches the file. Empty is none."""
        if text == self.instruction and not force:
            return
        self.instruction = text
        path = self.cfg.p2p.instruction
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        part.write_text(text + "\n")
        part.replace(path)
        self.trace.add("instruction", {"text": text})
        print(f'[p2p] instruction: "{text}"', flush=True)

    async def kev(
        self,
        purpose: str,
        prompt: str,
        questions: dict[str, Any],
        calls: list[dict[str, Any]],
        span: Span,
    ) -> dict[str, Any]:
        request = {"model": "kev-latest", "state": prompt, "questions": questions}
        started = time.monotonic()
        try:
            response = await self.client.post(self.cfg.kev.url, json=request)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            span.set_error("kev", exc)
            raise
        calls.append(
            {
                "purpose": purpose,
                "url": self.cfg.kev.url,
                "request": request,
                "response": body,
                "ms": round((time.monotonic() - started) * 1000),
            }
        )
        span.mark(
            {
                "do": "kev_do",
                "which": "kev_which",
                "then": "kev_then",
                "then: which": "kev_then_which",
                "speak": "kev_speak",
            }.get(purpose, purpose.replace(": ", "_"))
        )
        timings = body.get("timings")
        usage = body.get("usage")
        if timings:
            span.data.setdefault("timings", {})[purpose] = timings
        if usage:
            span.data.setdefault("usage", {})[purpose] = usage
        return body.get("answers", {})

    async def decide(
        self, to_player: bool, cooldown: bool, span: Span, noise: bool = False
    ) -> bool:
        started = time.monotonic()
        calls = []
        actions = self.state().get("actions", [])
        criteria, _ = joint_options(self.cfg.mate.name, actions, self.fill)
        questions: dict[str, Any] = {
            "do": {
                "type": "choice",
                "instructions": f"Which of these does {self.cfg.mate.name} do now?",
                "criteria": criteria,
            }
        }
        # The player's lines are answered unless they are noise; Kev scored real questions
        # ("what's your favorite color?") below 0.5 and answered only 45 of 108 real lines.
        ask_speak = not to_player and not cooldown
        if ask_speak:
            questions["speak"] = {
                "type": "noul",
                "instructions": f"Should {self.cfg.mate.name} speak now?",
            }
        if to_player:
            questions["is_command"] = {
                "type": "noul",
                "instructions": "Is the player's newest line asking Kevin to do something?",
            }
        answers = await self.kev("do", self.prompt(), questions, calls, span)
        done = await self.act("do", actions, calls, span, answers)
        chosen = next((a for a in actions if a.get("name") == done.get("action")), {})
        then = chosen.get("then") or []
        then_done = await self.act("then", then, calls, span) if then else None
        if to_player:
            speak = not noise
        else:
            speak = ask_speak and float(answers.get("speak", {}).get("noul", 0)) >= 0.5
        is_command = to_player and float(answers.get("is_command", {}).get("noul", 0)) >= 0.5
        if is_command:
            self._request_reflect("the player's newest line is a command")
        data = {
            "calls": calls,
            "action": done.get("action"),
            "option": done.get("option"),
            "sent": done.get("action") != "nothing",
            "seen": done.get("seen"),
            "then": then_done,
            "speak": speak,
            "speak_asked": ask_speak,
            "noise": noise,
            "is_command": is_command,
            "cooldown": cooldown,
            "ms": round((time.monotonic() - started) * 1000),
        }
        self.trace.add("kev", data)
        chain = str(done.get("action", "nothing"))
        if done.get("option"):
            chain += f" {done['option']}"
        if then_done:
            chain += f" -> {then_done.get('action', 'nothing')}"
        speak_note = "speak" if speak else ("noise" if noise else "quiet")
        speak_note = "cooldown" if cooldown else speak_note
        print(f"[kev] {chain}; {speak_note} ({data['ms']} ms)", flush=True)
        span.set(
            action=done.get("action"),
            option=done.get("option"),
            prompt_tokens_kev=len(self.prompt()) // 4,
        )
        return speak

    async def act(
        self,
        purpose: str,
        actions: list[dict[str, Any]],
        calls: list[dict[str, Any]],
        span: Span,
        answers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        name = self.cfg.mate.name
        options, choices = joint_options(name, actions, self.fill)
        prompt = self.prompt()
        if answers is None:
            q = {
                "do": {
                    "type": "choice",
                    "instructions": f"Which of these does {name} do now?",
                    "criteria": options,
                }
            }
            answers = await self.kev(purpose, prompt, q, calls, span)
        choice = str(answers.get("do", {}).get("choice", "nothing"))
        action, option = choices.get(choice, ("nothing", None))
        if action == "nothing":
            return {"action": action}
        chosen = next((a for a in actions if a.get("name") == action), {})
        msg: dict[str, Any] = {"type": "action", "action": action}
        line = options.get(action, "")
        targets = chosen.get("options") or {}
        if option is not None:
            msg["option"] = option
            line = f"{name} {self.fill(str(chosen.get('description', '')))}: {targets[option]}"
        elif len(targets) > 8:
            q = {
                "which": {
                    "type": "choice",
                    "instructions": f"{line}. Which one?",
                    "criteria": targets,
                }
            }
            answer = await self.kev(
                "which" if purpose == "do" else f"{purpose}: which", prompt, q, calls, span
            )
            msg["option"] = answer.get("which", {}).get("choice")
            if msg["option"] in targets:
                line += f": {targets[msg['option']]}"
        seen = None
        if chosen.get("view"):
            what, picture = await self.look(str(chosen["view"]), msg, span)
            line += f": {what}"
            seen = {"what": what, "picture": picture}
        else:
            await self.validator.send(
                self.state(),
                action,
                msg.get("option"),
                label=str(targets.get(msg.get("option"), "")),
            )
            if "result" in chosen:
                line += f": {self.fill(str(chosen['result']))}"
        self.memory.feed.append(line + ".")
        return {"action": action, "option": msg.get("option"), "seen": seen}

    async def look(self, kind: str, msg: dict[str, Any], span: Span) -> tuple[str, str | None]:
        started = time.monotonic()
        view = await self.link.view(2)
        if view is None:
            self.trace.add("sight", {"kind": kind, "error": "the game sent no view"})
            print(f"[sight] {kind}: no view", flush=True)
            return "he can't see it", None
        span.mark("look_view_received")
        choose = kind == "choose"
        if choose:
            mark(view.rgb, view.width, view.height, view.spots)
        data = png(view.rgb, view.width, view.height)
        filename = str(now_ms())
        (self.trace.session_dir / "views" / f"{filename}.png").write_bytes(data)
        name, player, game = self.cfg.mate.name, self.player(), self.state().get("game", "a game")
        eyes = (
            f"You're the eyes of {name}, {player}'s teammate in {game}: "
            f"you're shown what {player} is looking at."
        )
        if choose:
            system = (
                f"{eyes} Numbered spots are marked on the ground in it, and you pick the one "
                f"{name} goes to, from what's been said."
            )
            question = (
                f"Here's what {player} is looking at. Which spot does {name} go to? Answer "
                'with "place": what\'s at that spot, in a few words, and "spot": its number '
                "(0 if none fits)."
            )
        else:
            system = (
                f"{eyes} Say plainly what's there, in a sentence or two: what you see, "
                "not anyone's lines."
            )
            question = f"Here's what {player} is looking at. What's there?"
        newest = "\n".join(self.memory.feed[-12:])
        question = (
            f"{self.right_now()}\n\nWhat's been happening, newest last:\n{newest}\n\n{question}"
        )
        request = {
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{base64(data)}"},
                        },
                    ],
                },
            ],
            "temperature": self.cfg.llm.temperature,
            "stream": False,
            "id_slot": 1,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if choose:
            spots = [0, *[int(s["id"]) for s in view.spots if isinstance(s.get("id"), int)]]
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "spot",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "place": {"type": "string", "maxLength": 80},
                            "spot": {"type": "integer", "enum": spots},
                        },
                        "required": ["place", "spot"],
                    },
                },
            }
        traced = json.loads(json.dumps(request))
        traced["messages"][1]["content"][1]["image_url"]["url"] = f"/view?name={filename}"
        # Vision shares Gemma slot 1 with Reflect; waiting behind a Reflect run stalled replies 8 s.
        resume_reflect = await self._interrupt_reflect()
        try:
            response = await self.client.post(self.cfg.llm.url, json=request)
            response.raise_for_status()
            body = response.json()
            output = str(body.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
            if choose:
                answer = json.loads(output)
                spot = answer.get("spot", 0)
                if not isinstance(spot, int) or isinstance(spot, bool):
                    raise ValueError("vision response spot is not an integer")
                found = next((s for s in view.spots if spot > 0 and s.get("id") == spot), None)
                if found:
                    msg["option"] = str(spot)
                    await self.validator.send(
                        self.state(),
                        str(msg.get("action", "")),
                        str(spot),
                        label=str(answer.get("place", "")),
                    )
                    what = (
                        f"{str(answer.get('place', 'there')).strip()} ({found.get('metres')} m off)"
                    )
                else:
                    what = "none that fits"
            else:
                what = clean(output)
                self.validator.current = ActionStatus(str(msg.get("action", "")), status="done")
                self._validator_changed(self.validator.current)
        except Exception as exc:
            span.set_error("vision", exc)
            print(f"[sight] {kind}: error {exc}", flush=True)
            self.trace.add(
                "sight",
                {
                    "kind": kind,
                    "request": traced,
                    "picture": filename,
                    "error": str(exc),
                },
            )
            return "he can't see it", filename
        finally:
            if resume_reflect:
                self._request_reflect("resume after look")
        span.mark("look_done")
        self.trace.add(
            "sight",
            {
                "kind": kind,
                "url": self.cfg.llm.url,
                "request": traced,
                "output": output,
                "seen": what,
                "picture": filename,
                "spots": len(view.spots),
                "ms": round((time.monotonic() - started) * 1000),
            },
        )
        print(
            f"[sight] {kind}: {what} ({round((time.monotonic() - started) * 1000)} ms)",
            flush=True,
        )
        return what, filename

    async def say(self, span: Span) -> bool:
        name = self.cfg.mate.name
        messages = self.messages()
        self.learned = ""
        request = {
            "messages": messages,
            "temperature": self.cfg.llm.temperature,
            "stream": True,
            "id_slot": 0,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        resume_reflect = self.reflect_thinks and await self._interrupt_reflect()
        generation = self.speaking.generation
        started = time.monotonic()
        span.mark("llm_request")
        span.set(prompt_tokens_llm=len(json.dumps(messages, ensure_ascii=False)) // 4)
        full = ""
        notes = Notes()
        splitter = SentenceSplitter()
        how = ""
        directions = []
        first = None
        error = None
        model = None
        streaming_started = False
        try:
            async with self.client.stream("POST", self.cfg.llm.url, json=request) as response:
                response.raise_for_status()
                self.speaking.begin_line()
                streaming_started = True
                async for line in response.aiter_lines():
                    if self.speaking.generation != generation:
                        break
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    model = model or chunk.get("model")
                    if chunk.get("timings"):
                        span.set(llm_timings=chunk["timings"])
                    if chunk.get("usage"):
                        span.set(llm_usage=chunk["usage"])
                    choices = chunk.get("choices") or []
                    delta = choices[0].get("delta", {}).get("content") if choices else None
                    if delta is None:
                        continue
                    if first is None:
                        first = round((time.monotonic() - started) * 1000)
                        span.mark("llm_first_token")
                    full += delta
                    for piece in notes.push(delta):
                        if piece.kind is PieceKind.TEXT:
                            for sentence in splitter.push(piece.value):
                                await self._sentence(sentence, how, generation, span)
                        else:
                            if rest := splitter.finish():
                                await self._sentence(rest, how, generation, span)
                            how = delivery_note(piece.value)
                            if how:
                                directions.append(how)
        except Exception as exc:
            error = str(exc)
            span.set_error("llm", exc)
        if streaming_started:
            if rest := splitter.finish():
                await self._sentence(rest, how, generation, span)
            await self.speech.put(EndJob(generation, span))
        span.mark("llm_done")
        line = full.strip()
        if streaming_started:
            self.memory.feed.append(f"{name}: {line}")
            self._reflect_log(f"{name}: {line}")
        self.trace.add(
            "llm",
            {
                "url": self.cfg.llm.url,
                "model": model,
                "request": request,
                "output": full,
                "directions": directions,
                "line": line,
                "first_token_ms": first,
                "ms": round((time.monotonic() - started) * 1000),
                "cut_off": self.speaking.generation != generation,
                "error": error,
            },
        )
        total = round((time.monotonic() - started) * 1000)
        print(f'[llm] {name}: "{line}" (first {first} ms, total {total} ms)', flush=True)
        if resume_reflect:
            self._request_reflect("resume after voice")
        return streaming_started

    async def _interrupt_reflect(self) -> bool:
        task = self.reflect_task
        if not task or task.done():
            return False
        self.reflect_pending = False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def _sentence(self, text: str, how: str, generation: int, span: Span) -> None:
        text = text.strip()
        if text:
            if "first_sentence" not in span.data:
                span.mark("first_sentence")
            await self.speech.put(SentenceJob(text, how, generation, span))

    async def on_saved(self, ident: str) -> None:
        self.saves = [x for x in self.saves if x[0] != ident]
        self.saves.append(
            (
                ident,
                Memory(
                    self.memory.summary,
                    self.memory.feed.copy(),
                    self.memory.orders.copy(),
                    self.memory.remember.copy(),
                ),
            )
        )
        self.saves = self.saves[-SAVES:]
        self.saves_path.write_text(
            json.dumps(
                [
                    [
                        i,
                        {
                            "summary": m.summary,
                            "feed": m.feed,
                            "orders": m.orders,
                            "remember": m.remember,
                        },
                    ]
                    for i, m in self.saves
                ]
            )
        )
        self.trace.add("event", {"text": f"(the game saved: {ident})"})
        self.fold_over(FEED_TOKENS)

    async def on_loaded(self, ident: str) -> None:
        await self._cancel_reflect()
        found = next((m for i, m in reversed(self.saves) if i == ident), None)
        self.memory = (
            Memory(
                found.summary,
                found.feed.copy(),
                found.orders.copy(),
                found.remember.copy(),
            )
            if found
            else Memory()
        )
        self.memory_generation += 1
        self.summarizing = False
        self.reflect_log = []
        self.validator.current = None
        if self.cfg.p2p:
            self.set_instruction("")
        if self.play:
            self.play.reset()
        if self.speaking.is_speaking():
            self.speaking.interrupt()
            await self.link.send_json({"type": "stop_audio"})
        note = "memory restored" if found else "a save it never saw: memory cleared"
        self.trace.add("event", {"text": f"(the game loaded {ident}: {note})"})

    async def on_new_game(self, level: str) -> None:
        await self._cancel_reflect()
        self.memory = Memory()
        self.saves = []
        self.saves_path.write_text("[]")
        self.memory_generation += 1
        self.summarizing = False
        self.reflect_log = []
        self.validator.current = None
        if self.cfg.p2p:
            self.set_instruction("")
        if self.play:
            self.play.reset()
        self.speaking.interrupt()
        await self.link.send_json({"type": "stop_audio"})
        self.trace.add("event", {"text": f"(new game: {level}, memory reset)"})

    async def _cancel_reflect(self) -> None:
        self.reflect_pending = False
        task = self.reflect_task
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def on_summary(self, item: Summary) -> None:
        self.summarizing = False
        if item.memory_generation == self.memory_generation and item.folded <= len(
            self.memory.feed
        ):
            del self.memory.feed[: item.folded]
            self.memory.summary = item.text
            self.trace.add("memory", {"summary": item.text, "folded": item.folded})

    @staticmethod
    def feed_tokens(lines: list[str]) -> int:
        return sum(len(x) + 1 for x in lines) // 4

    def fold_over(self, limit: int) -> None:
        if self.summarizing or self.feed_tokens(self.memory.feed) <= limit:
            return
        folded = 0
        while (
            folded < len(self.memory.feed)
            and self.feed_tokens(self.memory.feed[folded:]) > FEED_FOLDED_TO
        ):
            folded += 1
        self.summarizing = True
        asyncio.create_task(
            self._summarize(
                folded,
                self.memory_generation,
                self.memory.summary,
                "\n".join(self.memory.feed[:folded]),
            )
        )

    async def _summarize(self, folded: int, generation: int, previous: str, lines: str) -> None:
        started = time.monotonic()
        name = self.cfg.mate.name
        request = (
            f"{previous}\n{lines}\n\nRewrite all of the above as {name}'s memory of what "
            f"happened: one paragraph of at most 250 words, past tense, about {name} in the "
            "third person. Keep every name, number and fact exactly as said (people, pets, "
            "places, plans, promises), and what matters for the story and the fights. Add "
            "nothing that isn't above. Leave out small talk that doesn't matter."
        )
        messages = [{"role": "user", "content": request}]
        output = None
        error = None
        model = None
        try:
            response = await self.client.post(
                self.cfg.llm.url,
                json={
                    "messages": messages,
                    "temperature": 0.3,
                    "id_slot": 1,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            response.raise_for_status()
            body = response.json()
            model = body.get("model")
            output = body.get("choices", [{}])[0].get("message", {}).get("content")
        except Exception as exc:
            error = str(exc)
        self.trace.add(
            "summary",
            {
                "messages": messages,
                "settings": {"url": self.cfg.llm.url, "temperature": 0.3, "model": model},
                "output": output,
                "ms": round((time.monotonic() - started) * 1000),
                "error": error,
            },
        )
        if output is not None:
            await self.inputs.put(Summary(generation, folded, clean(str(output))))
        else:
            self.summarizing = False
