"""Ticket 20261029-114343-review: "keep moving ahead of me, you keep stopping whenever I'm
stopping" got lead eight times, and lead held 6 m ahead of a standing player, right in front of
his gun: "Chief shot Kevin" (each answered keep) until Kevin died."""

from pathlib import Path

from m8py.skilltest import run_skill, situation
from m8py.skills import Library

LIBRARY = Library(Path(__file__).parents[1])


def go_points(sent):
    return [[float(v) for v in m["option"].split(",")] for m in sent if m["action"] == "go_point"]


def test_lead_keeps_walking_on_while_the_player_stands_still():
    states = situation("calm")[:12]  # the player stands at (0, -4) facing +y
    for step, state in enumerate(states):
        state["kevin"]["pos"] = [-4.0, 4.0, 0.0] if step < 6 else [-4.0, 10.0, 0.0]
    result, sent = run_skill(LIBRARY, "lead", states)
    assert result is None
    ys = [p[1] for p in go_points(sent)]
    assert ys[0] == 10.0 and 16.0 in ys  # at 8 m ahead already: on 6 m, and 6 m more


def test_lead_stays_off_the_players_line_of_aim():
    _, sent = run_skill(LIBRARY, "lead", situation("calm")[:4])  # aim at (3, 12): right of the path
    x, y, _ = go_points(sent)[0]
    assert x < -3 and y > 0  # the left side, clear of the shot


def test_lead_fails_when_blocked_on_both_sides():
    result, _ = run_skill(LIBRARY, "lead", situation("blocked"))
    assert result is not None and result.reason == "can't get ahead of the player: blocked"


def test_prompt_answers_one_friendly_fire_report_and_keeps_lead_on_go():
    prompt = (Path(__file__).parents[1] / "actor" / "prompt.md").read_text()
    assert "answer the first one" in prompt and '"keep moving ahead of me"' in prompt
    assert '"go, go, go"' in prompt and "while lead runs -> keep" in prompt
