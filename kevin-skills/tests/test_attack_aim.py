"""Ticket 20261029-112756-new_order: "right in front of me", an elite 13 m ahead of the player in
sight and two grunts 90 m off to the side out of sight (the actor had picked a far grunt)."""

from pathlib import Path

from m8py.skills import Failed, Library
from m8py.skilltest import run_skill, situation

LIBRARY = Library(Path(__file__).parents[1])


def shot_at(sent):
    return {m["option"] for m in sent if m["action"] == "shoot"}


def test_attack_aim_takes_the_enemy_in_front_of_the_player():
    states = situation("combat")
    for state in states:
        state["player"]["aim"] = {"pos": [0.0, 6.0, 0.0], "label": "ground", "distance_m": 10.0}
        state["enemies"] = [
            {"id": "570", "kind": "grunt", "health": 0.87, "pos": [-91.0, 0.0, 0.0], "distance_m": 91.0, "in_sight": False},
            {"id": "579", "kind": "elite", "health": 1.0, "pos": [2.0, 9.0, 0.0], "distance_m": 13.0, "in_sight": True},
            {"id": "50", "kind": "grunt", "health": 1.0, "pos": [-93.0, 3.0, 0.0], "distance_m": 93.0, "in_sight": False},
        ]
    assert shot_at(run_skill(LIBRARY, "attack", states[:6], target="aim")[1]) == {"579"}


def test_attack_aim_prefers_the_aimed_enemy_over_the_nearest():
    states = situation("combat")
    for state in states:
        state["player"]["aim"] = {"pos": [-6.0, 25.0, 0.0], "label": "elite", "distance_m": 29.6}
    assert shot_at(run_skill(LIBRARY, "attack", states[:6], target="aim")[1]) == {"32"}


def test_attack_aim_without_enemies():
    """Ticket 20261029-113205-failure: "shoot at that waterfall, shoot where I'm shooting", no
    enemies; attack failed twice. The reason must say he can't fire at things."""
    no_enemies = Failed("no enemies here: I can only shoot at enemies, not at things")
    states = situation("calm")
    for state in states:
        state["player"]["aim"] = {"pos": [0.0, 30.0, 5.0], "label": "waterfall", "distance_m": 34.0}
    assert run_skill(LIBRARY, "attack", states, target="aim") == (no_enemies, [])
    assert run_skill(LIBRARY, "attack", situation("calm"))[0] == no_enemies
