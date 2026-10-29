"""Tickets 20261029-093938-failure (go_to_aim at a wall) and 20261029-094022-new_order (push)."""

from pathlib import Path

from m8py.skills import Done, Failed, Library
from m8py.skilltest import run_skill, situation

LIBRARY = Library(Path(__file__).parents[1])


def points(sent):
    return [[float(v) for v in m["option"].split(",")] for m in sent if m["action"] == "go_point"]


def test_go_to_aim_stops_short_of_the_aim_on_the_players_side():
    _, sent = run_skill(LIBRARY, "go_to_aim", situation("calm"))
    assert points(sent)[0][1] < 12  # the boulder is at y=12, the player at y=-4


def test_go_to_aim_tries_closer_then_gives_up_when_blocked():
    result, sent = run_skill(LIBRARY, "go_to_aim", situation("blocked"))
    assert result == Failed("path blocked") and len(points(sent)) == 2


def test_push_rushes_the_nearest_enemy_and_ends_without_enemies():
    _, sent = run_skill(LIBRARY, "push", situation("combat"))
    assert sent[0] == {"type": "action", "action": "rush", "option": "31"}
    assert run_skill(LIBRARY, "push", situation("calm"))[0] == Done("no enemies to push")


def test_flank_refuses_a_target_up_in_the_air():
    states = situation("combat")
    for state in states:
        state["enemies"][0]["pos"][2] = 12.0  # still aboard the dropship
    result, sent = run_skill(LIBRARY, "flank", states, target="grunt#31")
    assert result == Failed("can't reach it: it's above or below me") and not sent


def test_flank_and_attack_without_a_target_take_the_nearest_or_say_there_is_none():
    assert run_skill(LIBRARY, "flank", situation("calm"))[0] == Failed("no enemy to flank")
    assert run_skill(LIBRARY, "attack", situation("calm"))[0] == Failed("no enemies here: I can only shoot at enemies, not at things")
    _, sent = run_skill(LIBRARY, "attack", situation("combat"))
    assert sent[0] == {"type": "action", "action": "shoot", "option": "31"}


def test_go_to_aim_heads_the_way_the_player_faces_when_the_aim_is_out_of_range():
    """Ticket 20261029-113319-new_order: "go run towards that waterfall", the waterfall too far for
    the game's aim point (aiming at nothing). go_to_aim failed; now he heads 30 m that way."""
    states = situation("calm")
    for step, state in enumerate(states):
        state["player"]["aim"] = {}
        state["kevin"]["pos"] = [0.0, min(step * 3.0, 26.0), 0.0]
    result, sent = run_skill(LIBRARY, "go_to_aim", states)
    assert result == Done("went 30 m that way")
    assert points(sent)[0] == [0.0, 26.0, 0.0]  # the player at y=-4 facing +y
    for state in (blocked := situation("blocked")):
        state["player"]["aim"] = {}
    result, sent = run_skill(LIBRARY, "go_to_aim", blocked)
    assert result == Failed("path blocked") and len(points(sent)) == 2


def test_go_to_a_far_waterfall_is_go_to_aim_and_bounded_by_health():
    """Ticket 20261029-113322-new_order: "go run towards that waterfall right now", right after
    go_to_aim failed, got nofit | lead. The prompt must send it to go_to_aim, and the long walk
    (ground 120 m off, patrols near it) must end on low health."""
    prompt = (Path(__file__).parents[1] / "actor" / "prompt.md").read_text()
    assert '"go to the waterfall" / "run towards that waterfall right now"' in prompt
    states = situation("calm")
    for step, state in enumerate(states):
        state["kevin"]["health"] = 1.0 if step < 3 else 0.2
    result, _ = run_skill(LIBRARY, "go_to_aim", states)
    assert result == Failed("low health")
