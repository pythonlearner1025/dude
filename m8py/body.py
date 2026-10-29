"""Kevin's body as skills see it (`k`): the companion state the game sends twice a second
(positions in metres, facing in degrees counter-clockwise from +x) and the companion's actions,
plus go_point. Commands collect in `outbox` and are sent after each step; repeats are dropped."""

from __future__ import annotations

import math
import time
from typing import Any, Iterator

Point = list[float]


def distance(a: Point | None, b: Point | None) -> float:
    if not a or not b:
        return math.inf
    return math.dist(a[:2], b[:2])


def toward(a: Point, b: Point) -> tuple[float, float]:
    """The unit vector from a to b on the ground (zero if they coincide)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > 1e-6 else (0.0, 0.0)


class Body:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {}
        self.time = time.monotonic()
        self.outbox: list[dict[str, Any]] = []
        self.runner: Any = None
        self._sent: tuple[str, str | None] | None = None
        self._sent_at = 0.0
        self._goal: Point | None = None
        self._best = math.inf
        self._best_at = 0.0

    # ---------- what the game says

    def update(self, state: dict[str, Any], now: float | None = None) -> None:
        self.state, self.time = state, time.monotonic() if now is None else now
        here = distance(self.me.get("pos"), self._goal)
        if here < self._best - 0.5:
            self._best, self._best_at = here, self.time

    @property
    def me(self) -> dict[str, Any]:
        return self.state.get("kevin") or {}

    @property
    def player(self) -> dict[str, Any]:
        return self.state.get("player") or {}

    @property
    def enemies(self) -> list[dict[str, Any]]:
        return [e for e in self.state.get("enemies") or [] if isinstance(e, dict)]

    def enemy(self, ident: Any) -> dict[str, Any] | None:
        ident = str(ident).split("#")[-1]
        return next((e for e in self.enemies if str(e.get("id")) == ident), None)

    def alive(self, ident: Any) -> bool:
        return self.enemy(ident) is not None

    def nearest_enemy(self, in_sight: bool = True) -> dict[str, Any] | None:
        pool = [e for e in self.enemies if e.get("in_sight") or not in_sight]
        return min(pool, key=lambda e: e.get("distance_m", math.inf), default=None)

    def offered(self, name: str) -> dict[str, Any] | None:
        def find(actions: list[dict[str, Any]]) -> dict[str, Any] | None:
            for action in actions:
                if action.get("name") == name:
                    return action
                if found := find(action.get("then") or []):
                    return found
            return None

        return find(self.state.get("actions") or [])

    def direction(self, pos: Point) -> str:
        """Where a point is from the player: ahead, behind, to the left or right."""
        here = self.player.get("pos")
        if not here or not pos:
            return "somewhere"
        angle = math.degrees(math.atan2(pos[1] - here[1], pos[0] - here[0]))
        turn = (angle - float(self.player.get("facing", 0)) + 180) % 360 - 180
        if abs(turn) <= 45:
            return "ahead"
        if abs(turn) >= 135:
            return "behind"
        return "to the left" if turn > 0 else "to the right"

    # ---------- geometry

    distance = staticmethod(distance)

    @staticmethod
    def ahead_of(pos: Point, facing: float, metres: float) -> Point:
        a = math.radians(facing)
        return [pos[0] + metres * math.cos(a), pos[1] + metres * math.sin(a), pos[2]]

    @staticmethod
    def side_point(target: Point, origin: Point, side: str, metres: float) -> Point:
        """A point `metres` to one side of target, as seen from origin (left/right of the line)."""
        fx, fy = toward(origin, target)
        lx, ly = -fy, fx  # left of the line from origin to target
        sign = -1 if side == "right" else 1
        return [target[0] + sign * lx * metres, target[1] + sign * ly * metres, target[2]]

    @staticmethod
    def behind(point: Point, away_from: Point, metres: float) -> Point:
        """A point `metres` past point, on the far side from away_from (behind cover)."""
        fx, fy = toward(away_from, point)
        return [point[0] + fx * metres, point[1] + fy * metres, point[2]]

    def stuck(self, seconds: float = 3.0) -> bool:
        """Short of the last go() point and no closer by half a metre for `seconds`."""
        far = distance(self.me.get("pos"), self._goal) > 1.5
        return self._goal is not None and far and self.time - self._best_at >= seconds

    # ---------- what Kevin does

    def fresh(self) -> None:
        """A new skill: its first commands are sent even if the last skill's were the same."""
        self._sent, self._goal = None, None

    def do(self, action: str, option: Any = None, every: float = 0.0) -> None:
        """Any companion action; the same one again is sent only after `every` seconds."""
        key = (action, None if option is None else str(option))
        if key == self._sent and (not every or self.time - self._sent_at < every):
            return
        message: dict[str, Any] = {"type": "action", "action": action}
        if option is not None:
            message["option"] = str(option)
        self.outbox.append(message)
        self._sent, self._sent_at = key, self.time
        if action != "go_point":
            self._goal = None

    def go(self, point: Point) -> None:
        """Walk to a point (metres) and stay there; resent only if the point moved 1 m or more."""
        going = self._sent is not None and self._sent[0] == "go_point"
        if going and self._goal is not None and distance(point, self._goal) < 1.0:
            return
        self._goal, self._best_at = list(point), self.time
        self._best = distance(self.me.get("pos"), point)
        self.do("go_point", ",".join(f"{v:.2f}" for v in point[:3]))

    def follow(self) -> None:
        self.do("follow")

    def stay(self) -> None:
        self.do("stay")

    def shoot(self, ident: Any) -> None:
        self.do("shoot", str(ident).split("#")[-1])

    def rush(self, ident: Any) -> None:
        self.do("rush", str(ident).split("#")[-1])

    def hold_fire(self) -> None:
        self.do("hold_fire")

    def cover(self) -> None:
        self.do("cover")

    def fall_back(self) -> None:
        self.do("fall_back")

    def crouch(self, on: bool = True) -> None:
        self.do("crouch" if on else "stand_up")

    def jump(self) -> None:
        self.do("jump", every=1.0)

    def melee(self, ident: Any) -> None:
        self.do("melee", str(ident).split("#")[-1], every=1.0)

    def grenade(self, ident: Any, kind: str = "frag") -> None:
        self.do(f"{kind}_grenade", str(ident).split("#")[-1], every=2.0)

    def pick_up(self, ident: Any) -> None:
        self.do("pick_up", ident)

    def switch_weapon(self) -> None:
        self.do("switch_weapon", every=2.0)

    def run(self, name: str, **args: Any) -> Iterator[None]:
        """Another skill's steps: `result = yield from k.run("attack", target=...)`."""
        return self.runner.steps(name, **args)
