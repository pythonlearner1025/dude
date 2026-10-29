"""Where the seed skills send Kevin, in the sample situations (m8py.skilltest.situation): the player
stands at (0, -4) facing +y, grunt#31 is near (4, 20), elite#32 at (-6, 25), and the player aims
at a boulder at (3, 12)."""

from pathlib import Path

from m8py.skills import Done, Library
from m8py.skilltest import run_skill, situation

LIBRARY = Library(Path(__file__).parents[1])


def first_point(sent):
    move = next(m for m in sent if m["action"] == "go_point")
    return [float(v) for v in move["option"].split(",")]


def test_flank_right_goes_to_the_players_right_of_the_enemy():
    _, sent = run_skill(LIBRARY, "flank", situation("combat"), target="grunt#31", side="right")
    assert first_point(sent)[0] > 10  # right of the line player -> grunt is +x


def test_behind_aim_goes_past_the_boulder_away_from_the_nearest_enemy():
    _, sent = run_skill(LIBRARY, "behind_aim", situation("combat"))
    x, y, _ = first_point(sent)
    assert y < 12  # the grunt is beyond the boulder, so behind it is nearer the player


def test_lead_goes_ahead_of_the_player():
    _, sent = run_skill(LIBRARY, "lead", situation("calm"))
    x, y, _ = first_point(sent)
    assert abs(x) < 0.5 and y > 0


def test_hold_fire_and_attack_end():
    assert run_skill(LIBRARY, "hold_fire", situation("calm"))[0] == Done("holding fire")
    result, sent = run_skill(LIBRARY, "attack", situation("dying"), target="grunt#31")
    assert result == Done("target down") and sent[0] == {
        "type": "action",
        "action": "shoot",
        "option": "31",
    }
