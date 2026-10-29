"""Checks a skill library before the coach commits it: every skill loads, is a generator with a
short, unique `when` line, and survives 30 steps of each sample situation; then the library's own
tests (tests/test_*.py, which can use run_skill and situation below) must pass.

Usage: python -m m8py.skilltest <library directory>
"""

from __future__ import annotations

import argparse
import copy
import inspect
import sys
from pathlib import Path
from typing import Any

from .body import Body
from .skills import Done, Failed, Library, Runner

STEPS = 30


def situation(kind: str = "calm") -> list[dict[str, Any]]:
    """Sample game states (two a second, as the game sends them): calm, combat (two grunts in
    sight), dying (the target dies after 5 states) or blocked (Kevin never moves)."""
    base = {
        "type": "state",
        "level": "a30",
        "in_combat": kind != "calm",
        "state": "Kevin: unhurt, shields full, holding an assault rifle. {player}: close by.",
        "kevin": {
            "pos": [0.0, 0.0, 0.0],
            "facing": 90.0,
            "health": 1.0,
            "shields": 1.0,
            "activity": "following",
        },
        "player": {
            "pos": [0.0, -4.0, 0.0],
            "facing": 90.0,
            "health": 1.0,
            "shields": 1.0,
            "aim": {"pos": [3.0, 12.0, 0.0], "label": "boulder", "distance_m": 16.0},
        },
        "enemies": [],
        "actions": [
            {
                "name": "search_weapons",
                "then": [
                    {
                        "name": "pick_up",
                        "options": {
                            "40": "assault rifle (3 m) ahead",
                            "41": "shotgun (6 m) to the left",
                        },
                    }
                ],
            }
        ],
    }
    states = []
    for step in range(STEPS):
        state = copy.deepcopy(base)
        if kind != "calm" and not (kind == "dying" and step >= 5):
            state["enemies"] = [
                {
                    "id": "31",
                    "kind": "grunt",
                    "health": 1.0,
                    "pos": [4.0, 20.0 - step * 0.2, 0.0],
                    "distance_m": 20.0,
                    "in_sight": True,
                },
                {
                    "id": "32",
                    "kind": "elite",
                    "health": 1.0,
                    "pos": [-6.0, 25.0, 0.0],
                    "distance_m": 25.7,
                    "in_sight": True,
                },
            ]
        if kind != "blocked":  # Kevin drifts forward
            state["kevin"]["pos"] = [0.0, step * 0.5, 0.0]
        states.append(state)
    return states


def run_skill(library: Library, name: str, states: list[dict[str, Any]], **args: Any):
    """Runs one skill over the states: (Done/Failed/None while still running, messages sent)."""
    body, ended = Body(), []
    runner = Runner(library, body, lambda running, result: ended.append(result))
    for step, state in enumerate(states):
        body.update(state, now=step * 0.5)
        if step == 0:
            error = runner.start(name, args)
            if error:
                return Failed(error), []
        runner.tick()
        if ended:
            break
    return (ended[0] if ended else None), body.outbox


def default_args(fn: Any, state: dict[str, Any]) -> dict[str, Any] | None:
    args = {}
    for name, param in list(inspect.signature(fn).parameters.items())[1:]:
        if param.default is not inspect.Parameter.empty:
            continue
        if name == "target" and state["enemies"]:
            args[name] = f"{state['enemies'][0]['kind']}#{state['enemies'][0]['id']}"
        else:
            return None  # needs an argument this situation can't give
    return args


def check(directory: Path) -> list[str]:
    problems = []
    library = Library(directory)
    problems += [f"{file} does not load:\n{error}" for file, error in library.errors.items()]
    seen: dict[str, str] = {}
    for found in library.skills.values():
        if not inspect.isgeneratorfunction(found.fn):
            problems.append(f"{found.name} is not a generator function")
            continue
        if len(found.when) > 140 or not found.when.strip():
            problems.append(f"{found.name}: `when` must be one line of at most 140 characters")
        if found.when in seen:
            problems.append(f"{found.name} and {seen[found.when]} have the same `when`")
        seen[found.when] = found.name
        for kind in ("calm", "combat", "dying", "blocked"):
            states = situation(kind)
            args = default_args(found.fn, states[0])
            if args is None:
                continue
            result, _ = run_skill(library, found.name, states, **args)
            if isinstance(result, Failed) and result.reason.startswith(("error", "no skill")):
                problems.append(f"{found.name} in a {kind} situation: {result.reason}")
            if result is not None and not isinstance(result, (Done, Failed)):
                problems.append(f"{found.name} returned {result!r}, not Done or Failed")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    directory = parser.parse_args().library.resolve()
    problems = check(directory)
    for problem in problems:
        print(f"FAIL {problem}")
    tests = directory / "tests"
    if tests.is_dir():
        import pytest

        sys.path.insert(0, str(directory))
        if pytest.main(["-q", str(tests)]) not in (0, 5):  # 5: no tests collected
            problems.append("library tests failed")
    if problems:
        raise SystemExit(1)
    print(f"ok: {len(Library(directory).skills)} skills")


if __name__ == "__main__":
    main()
