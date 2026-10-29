"""Ticket 20261029-110250-new_order: "switch to your other weapon"."""

from pathlib import Path

from m8py.skills import Done, Failed, Library
from m8py.skilltest import run_skill, situation

LIBRARY = Library(Path(__file__).parents[1])
PISTOL = "Kevin: unhurt, holding a pistol (12 rounds loaded, spare ammo), an assault rifle on his back (60 rounds loaded)."
RIFLE = "Kevin: unhurt, holding an assault rifle (60 rounds loaded), a pistol on his back (12 rounds loaded)."


def armed(switched_at=99):
    states = situation("calm")
    for step, state in enumerate(states):
        state["state"] = RIFLE if step >= switched_at else PISTOL
        state["actions"].append({"name": "switch_weapon", "description": "switches to his assault rifle"})
    return states


def test_switch_weapon_swaps_until_the_other_one_is_held():
    result, sent = run_skill(LIBRARY, "switch_weapon", armed(switched_at=2))
    assert result == Done("holding the assault rifle")
    assert [m["action"] for m in sent] == ["switch_weapon"]


def test_switch_weapon_by_name_and_without_a_second_weapon():
    assert run_skill(LIBRARY, "switch_weapon", armed(), kind="pistol")[0] == Done("already holding the pistol")
    assert run_skill(LIBRARY, "switch_weapon", armed(), kind="shotgun")[0] == Failed(
        "no shotgun; my other weapon is the assault rifle"
    )
    assert run_skill(LIBRARY, "switch_weapon", armed())[0] == Failed("couldn't switch")
    assert run_skill(LIBRARY, "switch_weapon", situation("calm"))[0] == Failed("no other weapon")
