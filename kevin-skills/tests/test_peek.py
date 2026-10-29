"""Ticket 20261029-112720-new_order: "stop hiding, peek out" with Kevin crouched behind a boulder
and the dropship's grunts out of sight."""

from pathlib import Path

from m8py.skills import Done, Failed, Library
from m8py.skilltest import run_skill, situation

LIBRARY = Library(Path(__file__).parents[1])


def behind_a_boulder(seen_from=4):
    """Kevin crouched at the origin; the enemies come into sight once he has stepped out."""
    states = situation("combat")
    for step, state in enumerate(states):
        state["kevin"]["pos"] = [-1.0 * min(step, 3), 0.0, 0.0] if step < 12 else [0.0, 0.0, 0.0]
        state["kevin"]["activity"] = "cover"
        for enemy in state["enemies"]:
            enemy["in_sight"] = seen_from <= step < 12
    return states


def test_peek_steps_out_shoots_and_ducks_back():
    result, sent = run_skill(LIBRARY, "peek", behind_a_boulder())
    actions = [m["action"] for m in sent]
    assert result is None  # still peeking: the enemies are alive
    assert actions[:2] == ["stand_up", "go_point"]
    assert {"action": "shoot", "option": "31", "type": "action"} in sent
    back = actions.index("shoot")
    assert "go_point" in actions[back:] and "crouch" in actions[back:]


def test_peek_ducks_back_when_the_shields_go():
    states = situation("combat")
    for step, state in enumerate(states):
        state["kevin"]["shields"] = max(0.0, 1.0 - step * 0.2) if step < 6 else 0.3
    result, sent = run_skill(LIBRARY, "peek", states[:20])
    assert result is None
    actions = [m["action"] for m in sent]
    assert actions[-1] == "crouch" and actions.count("shoot") == 1  # stopped shooting, back down


def test_peek_without_enemies():
    assert run_skill(LIBRARY, "peek", situation("calm"), target="grunt#31")[0] == Failed("no such enemy")
    assert run_skill(LIBRARY, "peek", situation("dying"), target="grunt#31")[0] == Done("target down")


def test_peek_with_no_enemies_looks_out_toward_the_aim_and_ducks_back():
    """Ticket 20261029-113152-new_order: "peek out and practice shooting at that waterfall", no
    enemies. Kevin steps out toward the aim, comes back crouched, and says he can't shoot scenery."""
    states = situation("calm")
    for state in states:
        state["kevin"]["pos"] = [0.0, 0.0, 0.0]
        state["player"]["aim"] = {"pos": [0.0, 30.0, 5.0], "label": "waterfall", "distance_m": 34.0}
    result, sent = run_skill(LIBRARY, "peek", states)
    assert result == Done("peeked out: no enemies in sight, and I can only shoot at enemies")
    actions = [m["action"] for m in sent]
    assert actions[0] == "stand_up" and "go_point" in actions and actions[-1] == "crouch"
    assert "shoot" not in actions


def test_the_calm_catalog_sends_shooting_at_scenery_to_peek():
    """Ticket 20261029-113205-new_order: "shoot at that waterfall, shoot where I'm shooting", no
    enemies, answered nofit | attack aim. With no enemies the catalog must show peek, and its
    when line (not attack's) must cover shooting at a thing."""
    calm = {s.name: s for s in LIBRARY.catalog({"core", "calm"})}
    assert "peek" in calm and "no enemies" in calm["peek"].when and "shoot at that" in calm["peek"].when
    assert "never scenery" in calm["attack"].when


def far_patrol_and_a_waterfall():
    """Ticket 20261029-113246-failure: "look at the waterfall and shoot it", an elite and grunts
    100+ m off to the side, out of sight; the actor answered attack aim, which failed."""
    states = situation("combat")
    for state in states:
        state["kevin"]["pos"] = [0.0, 0.0, 0.0]
        state["player"]["pos"] = [0.0, -6.0, 0.0]
        state["player"]["aim"] = {"pos": [0.0, 20.0, 0.0], "label": "ground", "distance_m": 26.0}
        state["enemies"] = [
            {"id": "618", "kind": "elite", "health": 1.0, "pos": [-103.0, -6.0, 0.0], "distance_m": 103.0, "in_sight": False},
            {"id": "599", "kind": "grunt", "health": 1.0, "pos": [-108.0, -4.0, 0.0], "distance_m": 108.0, "in_sight": False},
        ]
    return states


def test_shooting_at_scenery_with_only_far_enemies():
    states = far_patrol_and_a_waterfall()
    failed, sent = run_skill(LIBRARY, "attack", states, target="aim")
    assert failed == Failed("no enemy in front of you: I can only shoot at enemies, not at things")
    assert sent == []
    result, sent = run_skill(LIBRARY, "peek", states)
    assert result == Done("peeked out: no enemies in sight, and I can only shoot at enemies")
    actions = [m["action"] for m in sent]
    assert "go_point" in actions and actions[-1] == "crouch" and "shoot" not in actions


def test_the_combat_catalog_also_sends_shooting_at_scenery_to_peek():
    """Ticket 20261029-113246-new_order: "look at the waterfall and shoot it" with far, out-of-sight
    patrols known, so the actor saw the combat catalog: peek must be in it and the prompt must
    have the phrase."""
    combat = {s.name: s for s in LIBRARY.catalog({"core", "combat"})}
    assert "peek" in combat and "shoot at that" in combat["peek"].when
    prompt = (Path(__file__).parents[1] / "actor" / "prompt.md").read_text()
    assert '"look at the waterfall and shoot it" (enemies only 100 m off, out of sight) -> peek' in prompt
