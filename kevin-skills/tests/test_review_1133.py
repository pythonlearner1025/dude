"""Ticket 20261029-113343-review: Kevin stood in front of the player's gun; "Chief shot Kevin"
twenty times got keep or take_cover and he died twice."""

from pathlib import Path

from m8py.skills import Library
from m8py.skilltest import run_skill, situation

LIBRARY = Library(Path(__file__).parents[1])


def test_cover_player_steps_out_of_the_players_line_of_fire_before_shooting():
    states = situation("combat")[:8]
    for step, state in enumerate(states):  # player at y=-4 aiming at the boulder (3, 12)
        state["kevin"]["pos"] = [0.0, 4.0, 0.0] if step < 4 else [-3.0, 4.0, 0.0]
    result, sent = run_skill(LIBRARY, "cover_player", states)
    actions = [m["action"] for m in sent]
    assert result is None and actions[:2] == ["stand_up", "go_point"]
    assert float(sent[1]["option"].split(",")[0]) < 0  # to his left, away from the line
    assert "shoot" in actions[2:] and "shoot" not in actions[:2]


def test_cover_player_shoots_when_clear_and_the_prompt_sends_friendly_fire_to_it():
    states = situation("combat")[:4]
    for state in states:
        state["kevin"]["pos"] = [-4.0, 2.0, 0.0]
    _, sent = run_skill(LIBRARY, "cover_player", states)
    assert "go_point" not in [m["action"] for m in sent]
    prompt = (Path(__file__).parents[1] / "actor" / "prompt.md").read_text()
    assert '"Chief shot Kevin." / "you\'re in my way"' in prompt and "never take_cover for it" in prompt
