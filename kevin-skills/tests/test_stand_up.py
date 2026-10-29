"""Ticket 20261029-112826-new_order: "get up", "stop crouching" after take_cover left Kevin
crouched; follow ran but never stood him up."""

from pathlib import Path

from m8py.skills import Library
from m8py.skilltest import run_skill, situation

LIBRARY = Library(Path(__file__).parents[1])


def test_moving_skills_stand_kevin_up_first():
    for name in ("follow", "stay", "lead", "go_to_aim"):
        _, sent = run_skill(LIBRARY, name, situation("calm"))
        actions = [m["action"] for m in sent]
        assert actions[0] == "stand_up" and len(actions) > 1, name
