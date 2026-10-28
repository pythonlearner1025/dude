from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass(slots=True)
class ActionStatus:
    action: str
    option: str | None = None
    label: str = ""
    status: str = "sent"
    sent_at: float = 0.0
    last_distance: float | None = None
    last_progress_at: float | None = None

    def display(self) -> str:
        return f"{self.action}: {self.label}" if self.label else self.action


class Validator:
    """Validate offered actions and track the one current action from state v2."""

    def __init__(
        self,
        send: Callable[[dict[str, Any]], Awaitable[None]],
        changed: Callable[[ActionStatus], None],
        failed: Callable[[ActionStatus], None],
    ) -> None:
        self._send, self._changed, self._failed = send, changed, failed
        self.current: ActionStatus | None = None

    @staticmethod
    def offered(actions: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
        for action in actions:
            if action.get("name") == name:
                return action
            found = Validator.offered(action.get("then") or [], name)
            if found:
                return found
        return None

    async def send(
        self,
        state: dict[str, Any],
        action: str,
        option: str | None = None,
        *,
        label: str = "",
    ) -> bool:
        offered = self.offered(state.get("actions") or [], action)
        valid = offered is not None
        if valid and option is not None:
            options = offered.get("options") or {}
            valid = option in options or offered.get("view") == "choose"
        if valid and offered.get("options") and option is None:
            valid = False
        status = ActionStatus(action, option, label, "sent" if valid else "not available")
        status.sent_at = time.monotonic()
        self.current = status
        self._changed(status)
        if not valid:
            return False
        message: dict[str, Any] = {"type": "action", "action": action}
        if option is not None:
            message["option"] = option
        await self._send(message)
        return True

    def on_event(self, text: str) -> None:
        current = self.current
        if current and current.action in {"shoot", "rush"} and "Kevin killed" in text:
            self._finish("done")

    def update(self, state: dict[str, Any], now: float | None = None) -> None:
        current = self.current
        if not current or current.status in {"done", "failed", "not available"}:
            return
        now = time.monotonic() if now is None else now
        kevin = state.get("kevin")
        action = current.action
        if action in {"shoot", "rush"}:
            enemies = state.get("enemies")
            if not isinstance(enemies, list):
                return
            if current.option is not None and not any(
                str(enemy.get("id")) == current.option for enemy in enemies
            ):
                self._finish("done")
            else:
                self._set("in progress")
            return
        if not isinstance(kevin, dict):
            return
        activity = str(kevin.get("activity", ""))
        if action == "follow":
            if "activity" in kevin:
                if activity == "following":
                    self._finish("done")
                else:
                    self._set("in progress")
        elif action == "cover":
            if "activity" in kevin:
                if activity == "cover":
                    self._finish("done")
                else:
                    self._set("in progress")
        elif action == "get_in":
            if kevin.get("vehicle"):
                self._finish("done")
            elif activity == "going_to_vehicle":
                self._set("in progress")
        elif action in {"go_to", "go_aim"}:
            target = kevin.get("target")
            if not isinstance(target, dict):
                return
            distance = self._distance(kevin.get("pos"), target.get("pos"))
            if distance is None:
                return
            if distance <= 2:
                self._finish("done")
                return
            self._set("in progress")
            if current.last_distance is None or distance < current.last_distance - 0.05:
                current.last_distance = distance
                current.last_progress_at = now
            elif current.last_progress_at is not None and now - current.last_progress_at >= 5:
                self._set("failed")

    @staticmethod
    def _distance(a: Any, b: Any) -> float | None:
        if not (
            isinstance(a, list)
            and isinstance(b, list)
            and len(a) == len(b) == 3
            and all(isinstance(x, (int, float)) for x in [*a, *b])
        ):
            return None
        return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b, strict=True)))

    def _set(self, status: str) -> None:
        current = self.current
        if not current or current.status == status:
            return
        current.status = status
        self._changed(current)
        if status == "failed":
            self._failed(current)

    def _finish(self, status: str) -> None:
        if self.current and self.current.status == "sent":
            self._set("in progress")
        self._set(status)
