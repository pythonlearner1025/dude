from __future__ import annotations

import asyncio
import json
import struct
import time
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from aiohttp import WSMsgType, web

KIND_JSON, KIND_AUDIO, KIND_HEAR, KIND_VIEW = 1, 2, 3, 4


@dataclass(slots=True)
class View:
    width: int
    height: int
    rgb: bytearray
    spots: list[dict[str, Any]]


class GameLink:
    def __init__(
        self,
        hello: dict[str, Any],
        events: asyncio.Queue[dict[str, Any]],
        hearing: asyncio.Queue[tuple[dict[str, Any], np.ndarray, float]],
    ) -> None:
        self.hello, self.events, self.hearing = hello, events, hearing
        self.state: dict[str, Any] | None = None
        self.mic_muted = False
        self.speech_cooldown = 5.0
        self.writer: asyncio.StreamWriter | None = None
        self.websocket: web.WebSocketResponse | None = None
        self._writer_lock = asyncio.Lock()
        self._view_future: asyncio.Future[View] | None = None
        self.server: asyncio.Server | None = None
        self._logged_state = False
        self._logged_audio = False
        self.state_observers: list[Callable[[dict[str, Any]], None]] = []

    def add_state_observer(self, observer: Callable[[dict[str, Any]], None]) -> None:
        self.state_observers.append(observer)

    async def start(self, port: int, bind: str = "127.0.0.1") -> None:
        self.server = await asyncio.start_server(self._connected, bind, port)

    async def close(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        if self.websocket:
            await self.websocket.close()

    async def _connected(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.transport.set_write_buffer_limits(high=256 * 1024)
        old = self.writer
        old_websocket = self.websocket
        self.writer = writer
        self.websocket = None
        self._logged_state = self._logged_audio = False
        peer = writer.get_extra_info("peername")
        print(f"[game] connected {peer}", flush=True)
        if old and old is not writer:
            old.close()
        if old_websocket:
            await old_websocket.close()
        await self.send_json(self.hello)
        try:
            while True:
                header = await reader.readexactly(5)
                kind, length = header[0], struct.unpack(">I", header[1:])[0]
                payload = await reader.readexactly(length)
                await self.handle_frame(kind, payload)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            if self.writer is writer:
                self.writer = None
            writer.close()
            print(f"[game] disconnected {peer}", flush=True)

    async def websocket_connected(self, request: web.Request, ws: web.WebSocketResponse) -> None:
        """Use a WebSocket as the newest game link, treating messages as a byte stream."""
        old_writer = self.writer
        old_websocket = self.websocket
        self.writer = None
        self.websocket = ws
        self._logged_state = self._logged_audio = False
        peer = request.remote or "unknown"
        print(f"[game] connected {peer} (websocket)", flush=True)
        if old_writer:
            old_writer.close()
        if old_websocket and old_websocket is not ws:
            await old_websocket.close()
        await self.send_json(self.hello)
        buffered = bytearray()
        try:
            async for msg in ws:
                if msg.type != WSMsgType.BINARY:
                    continue
                buffered.extend(msg.data)
                while len(buffered) >= 5:
                    length = struct.unpack(">I", buffered[1:5])[0]
                    if length > 64 * 1024 * 1024:
                        await ws.close(code=1009, message=b"game frame too large")
                        return
                    if len(buffered) < 5 + length:
                        break
                    kind = buffered[0]
                    payload = bytes(buffered[5 : 5 + length])
                    del buffered[: 5 + length]
                    await self.handle_frame(kind, payload)
        finally:
            if self.websocket is ws:
                self.websocket = None
            print(f"[game] disconnected {peer} (websocket)", flush=True)

    async def handle_frame(self, kind: int, payload: bytes) -> None:
        received_at = time.monotonic()
        if kind in (KIND_HEAR, KIND_VIEW) and len(payload) >= 2:
            length = struct.unpack(">H", payload[:2])[0]
            try:
                about = json.loads(payload[2 : 2 + length])
            except (ValueError, UnicodeDecodeError):
                return
            body = payload[2 + length :]
            if kind == KIND_HEAR:
                samples = (
                    np.frombuffer(body[: len(body) // 2 * 2], dtype="<i2").astype(np.float32)
                    / 32768
                )
                await self.hearing.put((about, samples, received_at))
                return
            width, height = int(about.get("width", 0)), int(about.get("height", 0))
            if (
                width * height * 3 == len(body)
                and self._view_future
                and not self._view_future.done()
            ):
                self._view_future.set_result(
                    View(width, height, bytearray(body), about.get("spots", []))
                )
            return
        if kind != KIND_JSON:
            return
        try:
            msg = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            return
        match msg.get("type"):
            case "state":
                self.state = msg
                for observer in self.state_observers:
                    observer(msg)
                if not self._logged_state:
                    print("[game] received state", flush=True)
                    self._logged_state = True
            case "settings":
                if isinstance(msg.get("speech_cooldown"), (int, float)):
                    self.speech_cooldown = max(0.0, float(msg["speech_cooldown"]))
            case "mic":
                self.mic_muted = bool(msg.get("muted", False))
            case "new_game":
                # Do not expose the previous level while the fresh map is still loading.
                self.state = None
                msg["_received_at"] = received_at
                await self.events.put(msg)
            case "event" | "saved" | "loaded" | "direct" | "invite":
                msg["_received_at"] = received_at
                await self.events.put(msg)

    async def send_frame(self, kind: int, payload: bytes) -> None:
        async with self._writer_lock:
            packet = bytes([kind]) + struct.pack(">I", len(payload)) + payload
            websocket = self.websocket
            if websocket:
                try:
                    await websocket.send_bytes(packet)
                    if kind == KIND_AUDIO and not self._logged_audio:
                        print(f"[game] sent audio frame ({len(payload)} bytes)", flush=True)
                        self._logged_audio = True
                except (ConnectionError, RuntimeError):
                    if self.websocket is websocket:
                        self.websocket = None
                return
            if not self.writer:
                return
            try:
                self.writer.write(packet)
                await self.writer.drain()
                if kind == KIND_AUDIO and not self._logged_audio:
                    print(f"[game] sent audio frame ({len(payload)} bytes)", flush=True)
                    self._logged_audio = True
            except (ConnectionError, RuntimeError):
                self.writer = None

    async def send_json(self, value: dict[str, Any]) -> None:
        await self.send_frame(KIND_JSON, json.dumps(value, separators=(",", ":")).encode())

    async def send_audio(self, pcm: bytes) -> None:
        await self.send_frame(KIND_AUDIO, pcm)

    async def say(self, text: str) -> None:
        await self.send_json({"type": "say", "text": text})

    async def view(self, timeout: float = 2.0) -> View | None:
        self._view_future = asyncio.get_running_loop().create_future()
        await self.send_json({"type": "view"})
        try:
            return await asyncio.wait_for(self._view_future, timeout)
        except asyncio.TimeoutError:
            return None


def frame(kind: int, payload: bytes) -> bytes:
    return bytes([kind]) + struct.pack(">I", len(payload)) + payload
