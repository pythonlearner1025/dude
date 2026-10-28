import pytest

from m8py.validator import Validator


def make_validator():
    sent = []
    changed = []
    failed = []

    async def send(message):
        sent.append(message)

    validator = Validator(send, lambda current: changed.append(current.status), failed.append)
    return validator, sent, changed, failed


@pytest.mark.asyncio
async def test_validator_rechecks_latest_offer_and_option():
    validator, sent, changed, _ = make_validator()
    state = {
        "actions": [
            {"name": "shoot", "options": {"7": "grunt"}},
            {"name": "follow"},
        ]
    }
    assert await validator.send(state, "shoot", "7", label="grunt")
    assert sent == [{"type": "action", "action": "shoot", "option": "7"}]
    assert not await validator.send(state, "shoot", "gone")
    assert validator.current.status == "not available"
    assert changed[-1] == "not available"


@pytest.mark.asyncio
async def test_validator_v2_transitions_and_kill_event():
    validator, _, changed, _ = make_validator()
    state = {"actions": [{"name": "follow"}]}
    await validator.send(state, "follow")
    validator.update({"kevin": {"activity": "holding"}})
    validator.update({"kevin": {"activity": "following"}})
    assert changed == ["sent", "in progress", "done"]

    state = {"actions": [{"name": "shoot", "options": {"7": "grunt"}}]}
    await validator.send(state, "shoot", "7")
    validator.update({"enemies": [{"id": "7"}]})
    validator.on_event("Kevin killed a grunt.")
    assert validator.current.status == "done"


@pytest.mark.asyncio
async def test_validator_go_to_no_progress_fails_but_legacy_state_stays_sent():
    validator, _, changed, failed = make_validator()
    state = {"actions": [{"name": "go_aim"}]}
    await validator.send(state, "go_aim")
    validator.update({"state": "legacy prose only"}, now=0)
    assert validator.current.status == "sent"
    v2 = {"kevin": {"pos": [0, 0, 0], "target": {"pos": [10, 0, 0]}}}
    validator.update(v2, now=1)
    validator.update(v2, now=6)
    assert changed[-2:] == ["in progress", "failed"]
    assert failed == [validator.current]
