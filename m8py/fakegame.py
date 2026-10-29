from __future__ import annotations

import asyncio
import contextlib
import json
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp
import numpy as np
from PIL import Image

from .listen import decode_wav, resample
from .speak import wav_pcm

KIND_JSON, KIND_AUDIO, KIND_HEAR, KIND_VIEW = 1, 2, 3, 4


def _frame(kind: int, payload: bytes) -> bytes:
    return bytes([kind]) + struct.pack(">I", len(payload)) + payload


def _subframe(metadata: dict[str, Any], body: bytes) -> bytes:
    about = json.dumps(metadata, separators=(",", ":")).encode()
    return struct.pack(">H", len(about)) + about + body


def _compact(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


@dataclass(slots=True)
class InvariantResult:
    violations: list[str]
    messages: int
    audio_lines: int


class FakeGame:
    """A scripted TCP peer with the observable behavior of the Halo companion mod."""

    def __init__(
        self,
        scenario: str | Path | dict[str, Any],
        session_dir: str | Path,
        *,
        host: str = "127.0.0.1",
        port: int = 47800,
        site_url: str = "http://127.0.0.1:8090",
        mic_url: str = "ws://127.0.0.1:8091/mic",
        speed: float = 1.0,
    ) -> None:
        if isinstance(scenario, dict):
            self.scenario = scenario
            self.scenario_dir = Path.cwd()
        else:
            path = Path(scenario).resolve()
            self.scenario = json.loads(path.read_text())
            self.scenario_dir = path.parent
        self.session_dir = Path(session_dir)
        self.audio_dir = self.session_dir / "fakegame-audio"
        self.host, self.port = host, port
        self.site_url, self.mic_url = site_url.rstrip("/"), mic_url
        self.speed = max(0.01, speed)
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()
        self._log_lock = asyncio.Lock()
        self._started = 0.0
        self._hello = asyncio.Event()
        self._done = asyncio.Event()
        self._sample_rate = 24000
        self._line = 0
        self._line_pcm = bytearray()
        self._line_started: float | None = None
        self._last_say = ""
        self._offered: dict[str, set[str] | None] = {}
        self._violations: list[str] = []
        self._dead_targets: set[str] = set()
        self._audio_since_say = False
        self._allow_audio_after_stop = False
        self._awaiting_audio_end = False
        self.state = dict(self.scenario.get("initial_state", {}))

    async def run(self) -> InvariantResult:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(exist_ok=True)
        self._started = time.monotonic()
        await self._connect()
        reader_task = asyncio.create_task(self._read())
        state_task = asyncio.create_task(self._states())
        try:
            await self._hello.wait()
            await self.send_json(
                {"type": "settings", "speech_cooldown": self.scenario.get("speech_cooldown", 5)}
            )
            await self.send_json({"type": "mic", "muted": False})
            await self._timeline()
            await asyncio.sleep(float(self.scenario.get("settle", 3)) / self.speed)
        finally:
            self._done.set()
            state_task.cancel()
            await asyncio.gather(state_task, return_exceptions=True)
            if self.writer:
                self.writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await self.writer.wait_closed()
            await asyncio.gather(reader_task, return_exceptions=True)
            await self._finish_audio("disconnect")
        if self._awaiting_audio_end:
            self._violations.append("spoken line had no audio_end")
        return InvariantResult(self._violations, self._message_count(), self._line)

    async def _connect(self) -> None:
        retry = float(self.scenario.get("connect_retry", 2)) / self.speed
        while True:
            try:
                self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
                sock = self.writer.get_extra_info("socket")
                if sock:
                    sock.setsockopt(6, 1, 1)
                return
            except OSError:
                await asyncio.sleep(retry)

    async def _read(self) -> None:
        assert self.reader
        try:
            while True:
                header = await self.reader.readexactly(5)
                kind, length = header[0], struct.unpack(">I", header[1:])[0]
                payload = await self.reader.readexactly(length)
                if kind == KIND_AUDIO:
                    await self._audio(payload)
                elif kind == KIND_JSON:
                    await self._json(payload)
        except (asyncio.IncompleteReadError, ConnectionError):
            return

    async def _json(self, payload: bytes) -> None:
        try:
            msg = json.loads(payload)
        except (UnicodeDecodeError, ValueError):
            self._violations.append("invalid JSON from m8py")
            return
        await self.log("recv", message=msg)
        kind = msg.get("type")
        if kind == "hello":
            self._sample_rate = int(msg.get("sample_rate", 24000))
            self._hello.set()
        elif kind == "say":
            await self._finish_audio("next_say")
            self._line += 1
            self._line_started = time.time()
            self._last_say = str(msg.get("text", ""))
            self._awaiting_audio_end = True
            self._audio_since_say = False
            self._allow_audio_after_stop = False
        elif kind == "stop_audio":
            self._allow_audio_after_stop = not self._audio_since_say
            if self._audio_since_say:
                await self._finish_audio("stop_audio")
                self._awaiting_audio_end = False
        elif kind == "audio_end":
            await self._finish_audio("audio_end")
            self._awaiting_audio_end = False
            self._allow_audio_after_stop = False
        elif kind == "view":
            await self._send_view()
        elif kind == "action":
            self._check_action(msg)
            await self._consequence(msg)

    async def _audio(self, payload: bytes) -> None:
        if self._allow_audio_after_stop:
            self._allow_audio_after_stop = False
        elif not self._awaiting_audio_end:
            self._violations.append("audio arrived after stop_audio and before a new say")
        self._audio_since_say = True
        self._line_pcm.extend(payload)
        await self.log("recv_audio", bytes=len(payload), line=self._line)

    def _check_action(self, msg: dict[str, Any]) -> None:
        name = str(msg.get("action", ""))
        if name not in self._offered:
            self._violations.append(f"action {name!r} was not offered")
            return
        options = self._offered[name]
        option = msg.get("option")
        if options is not None and str(option) not in options:
            self._violations.append(f"option {option!r} was not offered for {name}")

    async def _consequence(self, msg: dict[str, Any]) -> None:
        name, option = str(msg.get("action", "")), str(msg.get("option", ""))
        text = str(self.state.get("state", ""))
        if name == "follow":
            text = text.replace(", holding his fire", "")
            if "following {player}" not in text:
                text = text.replace(". {player}:", ", following {player}. {player}:")
        elif name == "stay":
            text = text.replace(", following {player}", "")
        elif name == "hold_fire":
            text = text.replace(", shooting at the grunt", "").replace(
                ", shooting at the elite", ""
            )
            if "holding his fire" not in text:
                text = text.replace(". {player}:", ", holding his fire. {player}:")
        elif name == "pick_up":
            label = self._option_label(name, option).split(" (")[0]
            if label:
                before = text.split(", no second weapon", 1)[0]
                if "holding " in before:
                    replacement = (
                        f"Kevin: unhurt, shields full, holding a {label} "
                        "(8 rounds loaded, spare ammo)"
                    )
                    text = text.replace(before, replacement, 1)
        elif name in {"shoot", "rush", "frag_grenade", "plasma_grenade"}:
            target = self._option_label(name, option).split()[0] or "enemy"
            if "shooting at" not in text:
                text = text.replace(". {player}:", f", shooting at the {target}. {{player}}:")
            key = option or target
            if key not in self._dead_targets:
                self._dead_targets.add(key)
                delay = float(self.scenario.get("action_consequence_delay", 1.5)) / self.speed
                asyncio.create_task(self._kill_after(delay, target, option))
        self.state["state"] = text
        await self.log("consequence", action=name, option=option, state=text)

    def _option_label(self, name: str, option: str) -> str:
        for action in self.state.get("actions", []):
            candidates = [action, *(action.get("then") or [])]
            for candidate in candidates:
                if candidate.get("name") == name:
                    return str((candidate.get("options") or {}).get(option, ""))
        return ""

    async def _kill_after(self, delay: float, target: str, option: str) -> None:
        await asyncio.sleep(delay)
        if target and target in str(self.state.get("state", "")):
            actions = []
            targeted = {"shoot", "rush", "frag_grenade", "plasma_grenade", "melee"}
            for action in self.state.get("actions", []):
                options = action.get("options")
                if isinstance(options, dict):
                    options.pop(option, None)
                if action.get("name") not in targeted or options:
                    actions.append(action)
            self.state["actions"] = actions
            text = str(self.state.get("state", ""))
            text = text.replace(f", shooting at the {target}", "")
            if "Enemies: " in text:
                before, enemies = text.split("Enemies: ", 1)
                remaining = [
                    enemy.strip().rstrip(".")
                    for enemy in enemies.split(";")
                    if not enemy.strip().startswith(target)
                ]
                text = before + "Enemies: " + ("; ".join(remaining) if remaining else "none") + "."
                self.state["in_combat"] = bool(remaining)
            self.state["state"] = text
            await self._send_state()
            await self.send_json({"type": "event", "text": f"Kevin killed a {target}."})

    async def _states(self) -> None:
        rate = max(0.05, float(self.scenario.get("state_rate_hz", 2)))
        while not self._done.is_set():
            await self._hello.wait()
            await self._send_state()
            await asyncio.sleep(1 / rate / self.speed)

    async def _send_state(self) -> None:
        state = {
            "type": "state",
            "game": "Halo: Combat Evolved",
            "player_name": "Chief",
            "level": "a30",
            "in_combat": False,
            "on_radio": False,
            "state": (
                "Kevin is waiting. {player}: close by ahead, unhurt, shields full. Enemies: none."
            ),
            "actions": [],
            **self.state,
        }
        self._offered = {}
        for action in state.get("actions", []):
            self._offered[str(action.get("name"))] = (
                set(map(str, (action.get("options") or {}).keys()))
                if action.get("options")
                else None
            )
            for following in action.get("then") or []:
                self._offered[str(following.get("name"))] = (
                    set(map(str, (following.get("options") or {}).keys()))
                    if following.get("options")
                    else None
                )
        await self.send_json(state)

    async def _timeline(self) -> None:
        previous = 0.0
        for step in sorted(self.scenario.get("timeline", []), key=lambda x: x.get("at", 0)):
            at = float(step.get("at", 0))
            await asyncio.sleep(max(0, at - previous) / self.speed)
            previous = at
            await self._step(step)

    async def _step(self, step: dict[str, Any]) -> None:
        kind = step.get("kind")
        await self.log("scenario", step=step)
        if kind == "state":
            update = step.get("update", {})
            self.state.update(update)
            await self._send_state()
        elif kind == "event":
            await self._send_state()
            msg = {"type": "event", "text": step["text"]}
            if "react" in step:
                msg["react"] = bool(step["react"])
            await self.send_json(msg)
        elif kind in {"saved", "loaded"}:
            await self.send_json({"type": kind, "id": step["id"]})
        elif kind == "new_game":
            await self.send_json({"type": kind, "level": step["level"]})
        elif kind in {"direct", "mic"}:
            msg = {"type": kind, **{k: v for k, v in step.items() if k not in {"at", "kind"}}}
            await self.send_json(msg)
        elif kind == "player_text":
            async with aiohttp.ClientSession() as client:
                async with client.post(f"{self.site_url}/say", data=step["text"]) as response:
                    response.raise_for_status()
        elif kind == "player_wav":
            await self._stream_mic(self._fixture(step["file"]))
        elif kind == "dialogue":
            await self._send_dialogue(step)

    def _fixture(self, name: str) -> Path:
        path = Path(name)
        return path if path.is_absolute() else self.scenario_dir / path

    async def _stream_mic(self, path: Path) -> None:
        samples, rate = decode_wav(path.read_bytes())
        samples = resample(samples, rate, 16000)
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        silence = b"\0" * 640
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(self.mic_url) as ws:
                await ws.send_json({"type": "hello", "sample_rate": 16000})
                for start in range(0, len(pcm), 640):
                    await ws.send_bytes(pcm[start : start + 640])
                    await asyncio.sleep(0.02 / self.speed)
                for _ in range(15):
                    await ws.send_bytes(silence)
                    await asyncio.sleep(0.02 / self.speed)

    async def _send_dialogue(self, step: dict[str, Any]) -> None:
        samples, rate = decode_wav(self._fixture(step["file"]).read_bytes())
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        metadata = {
            "speaker": step.get("speaker", "Cortana"),
            "radio": bool(step.get("radio", True)),
            "react": bool(step.get("react", True)),
            "sample_rate": rate,
        }
        await self.send_frame(KIND_HEAR, _subframe(metadata, pcm))

    async def _send_view(self) -> None:
        view = self.scenario.get("view", {})
        path = self._fixture(str(view.get("file", "fixtures/view.png")))
        if path.exists():
            image = Image.open(path).convert("RGB")
            width, height = image.size
            rgb = image.tobytes()
        else:
            width, height = 320, 180
            y, x = np.mgrid[:height, :width]
            rgb = (
                np.dstack((40 + x // 3, 70 + y // 3, 60 + (x + y) // 8))
                .clip(0, 255)
                .astype("uint8")
                .tobytes()
            )
        spots = view.get(
            "spots",
            [
                {"id": 1, "x": 0.25, "y": 0.7, "metres": 9},
                {"id": 2, "x": 0.5, "y": 0.62, "metres": 16},
                {"id": 3, "x": 0.75, "y": 0.76, "metres": 7},
            ],
        )
        metadata = {"width": width, "height": height, "spots": spots}
        await self.send_frame(KIND_VIEW, _subframe(metadata, rgb))

    async def send_json(self, value: dict[str, Any]) -> None:
        await self.log("send", message=value)
        await self.send_frame(KIND_JSON, _compact(value))

    async def send_frame(self, kind: int, payload: bytes) -> None:
        async with self._write_lock:
            if not self.writer:
                return
            self.writer.write(_frame(kind, payload))
            await self.writer.drain()

    async def _finish_audio(self, reason: str) -> None:
        if not self._line_pcm or not self._line:
            return
        name = f"{self._line:03d}-{int((self._line_started or time.time()) * 1000)}.wav"
        (self.audio_dir / name).write_bytes(wav_pcm(bytes(self._line_pcm), self._sample_rate))
        await self.log(
            "audio_file",
            file=f"fakegame-audio/{name}",
            line=self._line,
            text=self._last_say,
            bytes=len(self._line_pcm),
            reason=reason,
        )
        self._line_pcm.clear()

    async def log(self, kind: str, **data: Any) -> None:
        record = {
            "t": time.time(),
            "elapsed": time.monotonic() - self._started,
            "kind": kind,
            **data,
        }
        async with self._log_lock:
            with (self.session_dir / "fakegame.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _message_count(self) -> int:
        path = self.session_dir / "fakegame.jsonl"
        return len(path.read_text().splitlines()) if path.exists() else 0


def check_invariants(session_dir: str | Path) -> list[str]:
    path = Path(session_dir) / "fakegame.jsonl"
    if not path.exists():
        return ["fakegame.jsonl is missing"]
    # Runtime legality depends on ephemeral offered snapshots and is checked by FakeGame.
    # Persisted checks cover line framing and stale audio ordering for independently run benches.
    entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    violations: list[str] = []
    open_line = False
    stopped = False
    audio_since_say = False
    allow_after_stop = False
    for entry in entries:
        msg = entry.get("message", {}) if entry.get("kind") == "recv" else {}
        if msg.get("type") == "say":
            open_line, stopped, audio_since_say = True, False, False
        elif msg.get("type") == "audio_end":
            if not open_line:
                violations.append("audio_end without a preceding say")
            open_line, stopped, allow_after_stop = False, False, False
        elif msg.get("type") == "stop_audio":
            allow_after_stop = open_line and not audio_since_say
            if not allow_after_stop:
                open_line, stopped = False, True
        elif entry.get("kind") == "recv_audio" and stopped:
            violations.append("audio after stop_audio before a new say")
            stopped = False
        elif entry.get("kind") == "recv_audio":
            audio_since_say = True
            allow_after_stop = False
    if open_line:
        violations.append("spoken line had no audio_end")
    return violations
