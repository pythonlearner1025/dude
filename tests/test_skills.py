import asyncio
import json
import os
import time

import httpx
import pytest

from m8py import skills
from m8py.actor import parse
from m8py.body import Body
from m8py.config import ActorConfig
from m8py.play import Play
from m8py.skills import Done, Failed, Library, Runner
from m8py.trace import Trace

SKILLS = """
from m8py.skills import Done, Failed, skill


@skill(when="stay behind the player", tags=("core",))
def follow(k):
    while True:
        k.follow()
        yield


@skill(when="shoot a target until it dies", args={"target": "enemy"}, tags=("core",))
def attack(k, target):
    while k.alive(target):
        k.shoot(target)
        yield
    return Done("target down")


@skill(when="go around an enemy", args={"target": "enemy", "side": "left or right"},
       tags=("combat",))
def flank(k, target, side="right"):
    enemy = k.enemy(target)
    if enemy is None:
        return Failed("no such enemy")
    k.go(k.side_point(enemy["pos"], k.player["pos"], side, 10))
    yield
    return (yield from k.run("attack", target=target))


@skill(when="breaks", tags=("calm",))
def broken(k):
    yield
    raise ValueError("bad")
"""


def state(enemies=()):
    return {
        "type": "state",
        "level": "a30",
        "state": "Kevin: unhurt. {player}: close by.",
        "kevin": {"pos": [0.0, 0.0, 0.0], "facing": 0.0, "health": 1.0, "shields": 1.0},
        "player": {"pos": [0.0, -5.0, 0.0], "facing": 90.0, "health": 1.0, "aim": {}},
        "enemies": [
            {"id": str(i), "kind": "grunt", "pos": p, "distance_m": 10, "in_sight": True}
            for i, p in enemies
        ],
        "actions": [],
    }


@pytest.fixture
def library(tmp_path):
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "basic.py").write_text(SKILLS)
    return Library(tmp_path)


def test_library_catalog_and_hot_reload(library, tmp_path):
    assert sorted(library.skills) == ["attack", "broken", "flank", "follow"]
    assert [s.name for s in library.catalog(set())] == ["follow", "attack", "flank", "broken"]
    skills.MAX_CATALOG, saved = 3, skills.MAX_CATALOG  # past the limit, tags choose
    try:
        assert [s.name for s in library.catalog({"combat"})] == ["follow", "attack", "flank"]
    finally:
        skills.MAX_CATALOG = saved
    assert library.skills["flank"].line().startswith("flank(target, side=right)  go around")
    assert not library.changed()
    path = tmp_path / "skills" / "basic.py"
    path.write_text("syntax error here (")
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert library.changed()
    library.load()
    assert "basic.py" in library.errors and "flank" in library.skills  # the old version stays


def test_runner_steps_ends_and_composes(library):
    ended = []
    body = Body()
    runner = Runner(library, body, lambda running, result: ended.append(result))
    body.update(state([("31", [10.0, 0.0, 0.0])]))
    assert runner.start("flank", {"target": "grunt#31", "nope": 1}).startswith("flank takes")
    assert runner.start("flank", {"target": "grunt#31"}) is None
    runner.tick()
    assert body.outbox[-1]["action"] == "go_point"
    runner.tick()  # now attacking
    assert body.outbox[-1] == {"type": "action", "action": "shoot", "option": "31"}
    body.update(state())  # the grunt is gone
    runner.tick()
    assert ended == [Done("target down")] and runner.current is None
    body.go([5.0, 0.0, 0.0])
    sent = len(body.outbox)
    runner.start("flank", {"target": "grunt#31"})  # a new skill sends its first command again
    body.update(state([("31", [10.0, 0.0, 0.0])]))
    runner.tick()
    assert len(body.outbox) == sent + 1 and not body.stuck(0.1)
    runner.start("broken", {})
    runner.tick()
    runner.tick()
    assert isinstance(ended[-1], Failed) and ended[-1].reason.startswith("error: ValueError")


def test_parse_is_lenient(library):
    assert parse("flank grunt#31 left", library).args == {"target": "grunt#31", "side": "left"}
    assert parse("`flank(grunt#31, side=left)`\n", library).args == {
        "target": "grunt#31",
        "side": "left",
    }
    assert parse("keep.", library).kind == "keep"
    nofit = parse("nofit push them off the ridge | attack grunt#2", library)
    assert (nofit.kind, nofit.order, nofit.skill) == ("nofit", "push them off the ridge", "attack")
    assert parse("dance wildly", library).kind == "invalid"


def test_body_geometry_and_repeats():
    body = Body()
    body.update(state(), now=0.0)
    assert body.direction([0.0, 5.0, 0.0]) == "ahead"  # the player faces +y
    assert body.direction([-5.0, -5.0, 0.0]) == "to the left"
    assert body.side_point([10, 0, 0], [0, 0, 0], "right", 4) == pytest.approx([10, -4, 0])
    assert body.behind([10, 0, 0], [0, 0, 0], 2) == pytest.approx([12, 0, 0])
    body.go([5.0, 0.0, 0.0])
    body.go([5.3, 0.0, 0.0])  # less than a metre: not sent again
    body.follow()
    body.follow()
    assert [m["action"] for m in body.outbox] == ["go_point", "follow"]
    body.go([20.0, 0.0, 0.0])
    body.update(state(), now=4.0)
    assert body.stuck(3.0)


def sse(text):
    chunks = [{"choices": [{"delta": {"content": text}}]}, {"choices": [], "usage": {"x": 1}}]
    data = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, text=data, headers={"content-type": "text/event-stream"})


class Link:
    def __init__(self):
        self.sent = []

    async def send_json(self, message):
        self.sent.append(message)


@pytest.mark.asyncio
async def test_play_decides_retries_and_writes_tickets(cfg, library, tmp_path):
    answers = iter(["dance", "flank grunt#31", "nofit push them off | attack grunt#31"])
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return sse(next(answers))

    cfg.kev = None
    cfg.actor = ActorConfig(
        model="m", library=library.directory, tickets=tmp_path / "tickets", provider="together"
    )
    trace = Trace(tmp_path / "logs")
    trace.start()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    play = Play(cfg, Link(), trace, client, lambda: ["hold fire"], lambda t: t)
    play.on_state(state([("31", [10.0, 0.0, 0.0])]))
    decision = await play.decide(['the player said "flank him"'])
    assert decision.skill == "flank" and play.runner.current.skill.name == "flank"
    body = requests[0]
    assert body["provider"] == {"only": ["together"], "allow_fallbacks": False}
    assert body["reasoning"] == {"enabled": False}
    assert "flank(target, side=right)" in body["messages"][0]["content"]
    assert "grunt#31 10 m" in body["messages"][1]["content"]
    assert "Orders: hold fire." in body["messages"][1]["content"]
    assert "could not run" in requests[1]["messages"][1]["content"]
    await play.decide(['the player said "push them off the ridge"'])
    tickets = list((tmp_path / "tickets").glob("*.json"))
    assert [json.loads(t.read_text())["order"] for t in tickets] == ["push them off"]
    await asyncio.sleep(0)
    await client.aclose()
    await trace.close()


def test_seed_library_passes_skilltest():
    from pathlib import Path

    from m8py.skilltest import check

    assert check(Path(__file__).parents[1] / "kevin-skills") == []


def test_coach_takes_oldest_ticket_and_one_review(tmp_path):
    from m8py.coach import pending

    for name in ["1-new_order", "2-review", "3-failure", "4-review"]:
        (tmp_path / f"{name}.json").write_text("{}")
    (tmp_path / "3-failure.result.md").write_text("done")
    assert [p.stem for p in pending(tmp_path)] == ["1-new_order", "4-review"]
    assert (tmp_path / "2-review.result.md").exists()
