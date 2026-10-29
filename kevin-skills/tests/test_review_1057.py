"""Ticket 20261029-105757-review: clear_area fought on until an elite took Kevin from 35% shields
to dead in a second; the 25% health check never got a chance."""

from pathlib import Path

from m8py.skills import Done, Failed, Library
from m8py.skilltest import run_skill, situation

LIBRARY = Library(Path(__file__).parents[1])


def losing_shields():
    states = situation("combat")
    for step, state in enumerate(states):
        state["kevin"]["shields"] = max(0.0, 1.0 - step * 0.15)
    return states


def test_fights_break_off_when_the_shields_go():
    assert run_skill(LIBRARY, "clear_area", losing_shields())[0] == Failed("shields down")
    assert run_skill(LIBRARY, "push", losing_shields())[0] == Failed("shields down")


def test_take_cover_waits_in_cover_for_the_shields():
    states = situation("combat")
    for step, state in enumerate(states):
        state["kevin"]["activity"] = "cover"
        state["kevin"]["shields"] = min(1.0, step * 0.1)
    assert run_skill(LIBRARY, "take_cover", states)[0] == Done("in cover")
    assert run_skill(LIBRARY, "take_cover", states[:5])[0] is None  # still recharging at 40%
    unhurt = situation("calm")
    for state in unhurt:
        state["kevin"]["activity"] = "cover"
    assert run_skill(LIBRARY, "take_cover", unhurt)[0] == Done("in cover")
