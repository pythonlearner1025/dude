from __future__ import annotations

import asyncio
import time


class Speaking:
    TAIL = 0.5

    def __init__(self) -> None:
        self.until = time.monotonic()
        self.generation = 0
        self.lines = 0
        self._lock = asyncio.Lock()

    def begin_line(self) -> None:
        self.lines += 1

    def end_line(self) -> None:
        self.lines = max(0, self.lines - 1)

    def quiet_from(self) -> float | None:
        return self.until if self.lines == 0 else None

    def extend(self, seconds: float) -> None:
        self.until = max(self.until, time.monotonic()) + seconds

    def is_speaking(self) -> bool:
        return time.monotonic() < self.until + self.TAIL

    def interrupt(self) -> None:
        self.generation += 1
        self.until = time.monotonic() - self.TAIL
