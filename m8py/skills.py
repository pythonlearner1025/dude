"""Kevin's skills: generator functions in a library directory (written by the coach, a frontier
model in Claude Code), run one at a time, one step per game state. The actor picks them by name
from a catalog built from their @skill metadata (docs/design/kevin-skill-loop.html)."""

from __future__ import annotations

import importlib.util
import inspect
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

MAX_CATALOG = 20


@dataclass(slots=True)
class Done:
    reason: str = "done"


@dataclass(slots=True)
class Failed:
    reason: str


@dataclass(slots=True)
class Skill:
    name: str
    fn: Callable[..., Iterator[None]]
    when: str
    args: dict[str, str]
    done: str = ""
    tags: tuple[str, ...] = ()
    source: str = ""

    def line(self) -> str:
        params = inspect.signature(self.fn).parameters
        shown = [
            name if p.default is inspect.Parameter.empty else f"{name}={p.default!r}"
            for name, p in list(params.items())[1:]
        ]
        return f"{self.name}({', '.join(shown)})  {self.when}"


_loading: list[Skill] = []


def skill(
    when: str, args: dict[str, str] | None = None, done: str = "", tags: tuple[str, ...] = ()
) -> Callable[[Callable[..., Iterator[None]]], Callable[..., Iterator[None]]]:
    """Marks a generator function in the library as a skill; `when` is all the actor sees."""

    def mark(fn: Callable[..., Iterator[None]]) -> Callable[..., Iterator[None]]:
        _loading.append(Skill(fn.__name__, fn, when, args or {}, done, tuple(tags)))
        return fn

    return mark


class Library:
    """skills/*.py of a library directory. A file that fails to load keeps its previous skills."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.skills: dict[str, Skill] = {}
        self.errors: dict[str, str] = {}
        self._stamp: tuple = ()
        self.load()

    def stamp(self) -> tuple:
        return tuple(
            (p.name, p.stat().st_mtime_ns) for p in sorted(self.directory.glob("skills/*.py"))
        )

    def changed(self) -> bool:
        return self.stamp() != self._stamp

    def load(self) -> None:
        self._stamp = self.stamp()
        loaded: dict[str, Skill] = {}
        for path in sorted(self.directory.glob("skills/*.py")):
            _loading.clear()
            name = f"kevin_skills_{path.stem}_{time.monotonic_ns()}"
            try:
                spec = importlib.util.spec_from_file_location(name, path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)
            except Exception:
                self.errors[path.name] = traceback.format_exc(limit=3)
                loaded.update({s.name: s for s in self.skills.values() if s.source == path.name})
                continue
            finally:
                sys.modules.pop(name, None)
            self.errors.pop(path.name, None)
            for found in _loading:
                found.source = path.name
                loaded[found.name] = found
        self.skills = loaded

    def catalog(self, tags: set[str]) -> list[Skill]:
        """Every skill while they fit in MAX_CATALOG, core first; past that, the core skills
        and those tagged for the moment (a skill left out can only be answered with nofit)."""
        core = [s for s in self.skills.values() if "core" in s.tags]
        if len(self.skills) <= MAX_CATALOG:
            return core + [s for s in self.skills.values() if "core" not in s.tags]
        fitting = [s for s in self.skills.values() if "core" not in s.tags and tags & set(s.tags)]
        return (core + fitting)[:MAX_CATALOG]


@dataclass(slots=True)
class Running:
    skill: Skill
    args: dict[str, Any]
    steps: Iterator[None]
    started: float = field(default_factory=time.monotonic)

    def display(self) -> str:
        args = " ".join(str(v) for v in self.args.values())
        return f"{self.skill.name} {args}".strip()


class Runner:
    """Runs one skill at a time against the body, one step per game state."""

    def __init__(
        self, library: Library, body: Any, ended: Callable[[Running, Done | Failed], None]
    ):
        self.library, self.body, self.ended = library, body, ended
        self.current: Running | None = None
        body.runner = self

    def start(self, name: str, args: dict[str, Any]) -> str | None:
        """Starts a skill in place of the current one; an error message if it can't."""
        found = self.library.skills.get(name)
        if not found:
            return f"no skill called {name}"
        params = list(inspect.signature(found.fn).parameters)[1:]
        unknown = [a for a in args if a not in params]
        if unknown:
            return f"{name} takes {', '.join(params) or 'no arguments'}, not {', '.join(unknown)}"
        try:
            steps = found.fn(self.body, **args)
        except TypeError as exc:
            return f"{name}: {exc}"
        if not inspect.isgenerator(steps):
            return f"{name} is not a generator"
        self.stop()
        self.body.fresh()
        self.current = Running(found, args, steps)
        return None

    def stop(self) -> None:
        if self.current:
            self.current.steps.close()
            self.current = None

    def steps(self, name: str, **args: Any) -> Iterator[None]:
        """Another skill's steps, for `yield from k.run(...)` inside a skill."""
        return self.library.skills[name].fn(self.body, **args)

    def tick(self) -> None:
        running = self.current
        if not running:
            return
        try:
            next(running.steps)
            return
        except StopIteration as stop:
            result = stop.value if isinstance(stop.value, (Done, Failed)) else Done()
        except Exception as exc:
            where = traceback.extract_tb(exc.__traceback__)[-1]
            result = Failed(f"error: {type(exc).__name__}: {exc} (line {where.lineno})")
        if self.current is running:
            self.current = None
        self.ended(running, result)
