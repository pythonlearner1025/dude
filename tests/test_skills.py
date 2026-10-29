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


@skill(when='shoot a target until it dies: "shoot it"', args={"target": "enemy"}, tags=("core",))
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
    assert library.skills["flank"].line().startswith("flank(target, side='right')  go around")
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

    async def view(self, timeout):
        from m8py.link import View

        return View(4, 2, bytearray(range(24)), [])


@pytest.mark.asyncio
async def test_play_decides_retries_and_traces_for_the_coach(cfg, library, tmp_path):
    answers = iter(["dance", "flank grunt#31", "attack grunt#31"])
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return sse(next(answers))

    cfg.kev = None
    cfg.actor = ActorConfig(model="m", library=library.directory, provider="together")
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
    assert "flank(target, side='right')" in body["messages"][0]["content"]
    assert "nofit" not in body["messages"][0]["content"]
    assert "grunt#31 10 m" in body["messages"][1]["content"]
    assert "Orders: hold fire." in body["messages"][1]["content"]
    assert "could not run" in requests[1]["messages"][1]["content"]
    play.trigger('the player said "kill him"')  # a frame of what the player sees
    await play.decide(['the player said "kill him"'])
    for _ in range(20):
        await asyncio.sleep(0.01)
    await client.aclose()
    await trace.close()
    rows = [json.loads(line) for line in (trace.session_dir / "trace.jsonl").open()]
    kinds = [row["kind"] for row in rows]
    assert "ticket" not in kinds and kinds.count("decision") == 2
    seen = next(row["data"] for row in rows if row["kind"] == "state")
    assert seen["kevin"]["pos"] == [0.0, 0.0, 0.0] and seen["enemies"][0]["id"] == "31"
    view = next(row["data"] for row in rows if row["kind"] == "view")
    assert view["why"] == "the player spoke"
    assert (trace.session_dir / view["file"]).read_bytes()[:2] == b"\xff\xd8"  # a JPEG


def test_seed_library_passes_skilltest():
    from pathlib import Path

    from m8py.skilltest import check

    assert check(Path(__file__).parents[1] / "kevin-skills") == []


def session_trace(logs, rows):
    session = logs / "1793000000"
    (session / "views").mkdir(parents=True)
    (session / "views" / "1793000005000.jpg").write_bytes(b"\xff\xd8 a frame")
    with (session / "trace.jsonl").open("w") as out:
        for i, (t, kind, data) in enumerate(rows):
            out.write(json.dumps({"id": str(i), "t": str(t), "kind": kind, "data": data}) + "\n")
    return session / "trace.jsonl"


PLAYED = [
    (
        1793000001000,
        "state",
        {
            "level": "a30",
            "kevin": {"pos": [0, 0, 0], "health": 1.0},
            "player": {"pos": [0, -5, 0], "aim": None},
            "enemies": [],
        },
    ),
    (1793000002000, "heard", {"text": "Kevin, take point."}),
    (
        1793000002300,
        "decision",
        {
            "reasons": ['the player said "Kevin, take point."'],
            "answer": "lead",
            "kind": "start",
            "ms": 190,
        },
    ),
    (1793000002400, "body", {"sent": [{"action": "go_point", "option": "0,6,0"}]}),
    (1793000003000, "decision", {"reasons": ["heartbeat"], "answer": "keep", "kind": "keep"}),
    (1793000004000, "event", {"text": "Chief shot Kevin."}),
    (1793000005000, "view", {"file": "views/1793000005000.jpg", "why": "the player spoke"}),
    (1793000009000, "skill", {"skill": "lead", "args": {}, "failed": "blocked"}),
]


def test_observation_packet(tmp_path):
    from m8py.observe import active, build, render, rows_between

    trace = session_trace(tmp_path, PLAYED)
    assert active(rows_between(trace, 0, 1793000001500)) is False  # only the game's state
    assert active(rows_between(trace, 1793000001500, 1793000009000)) is False  # no game
    packet = build(trace, 0, 1793000009000, "s-001", {"head": "abc1234"}, None)
    assert packet["level"] == "a30" and packet["counts"]["player_lines"] == 1
    assert packet["counts"]["heartbeat_keeps"] == 1 and packet["counts"]["friendly_fire"] == 1
    assert [e["type"] for e in packet["timeline"]] == [
        "state",
        "player",
        "decision",
        "command",
        "game",
        "frame",
        "skill",
    ]
    text = render(packet)
    assert 'PLAYER   "Kevin, take point."' in text and "=> lead (190 ms)" in text
    assert "SKILL    lead -> FAILED: blocked" in text and "HALO     go_point 0,6,0" in text


def test_coach_looks_on_a_heartbeat(tmp_path):
    import subprocess

    from m8py.coach import look

    library, other = tmp_path / "library", tmp_path / "other"
    for repo in (library, other):
        (repo / "skills").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
    trace = session_trace(tmp_path / "logs", PLAYED)
    claude = tmp_path / "claude"
    claude.write_text(  # Claude's shell wandered into another repo, then committed
        f"#!/bin/sh\ncd {other} && touch $GIT_WORK_TREE/skills/new.py && git add -A && "
        "git -c user.name=c -c user.email=c@c commit -qm fix\n"
    )
    claude.chmod(0o755)
    out = tmp_path / "observations"
    assert look(trace, library, out, 1, "m", "high", 30, str(claude)) == "looked"
    packet = out / "1793000000" / "001"
    assert "take point" in (packet / "packet.md").read_text()
    assert (packet / "frames" / "1793000005000.jpg").exists()
    assert "stopped without a result" in (packet / "result.md").read_text()
    log = ["git", "log", "--format=%s"]
    assert subprocess.run(log, cwd=library, capture_output=True, text=True).stdout == "fix\n"
    assert subprocess.run(log, cwd=other, capture_output=True, text=True).returncode != 0
    assert look(trace, library, out, 1, "m", "high", 30, str(claude)) == "waiting"  # seen it all


@pytest.mark.asyncio
async def test_play_restarts_a_changed_skill_and_tells_the_player(cfg, tmp_path):
    import subprocess

    lib = tmp_path / "lib"
    (lib / "skills").mkdir(parents=True)
    path = lib / "skills" / "basic.py"
    path.write_text(SKILLS)
    commit = ["git", "-C", str(lib), "-c", "user.name=c", "-c", "user.email=c@c", "commit", "-qam"]
    subprocess.run(["git", "init", "-q", str(lib)], check=True)
    subprocess.run(["git", "-C", str(lib), "add", "-A"], check=True)
    subprocess.run([*commit, "seed"], check=True)
    cfg.kev = None
    cfg.actor = ActorConfig(model="m", library=lib)
    trace = Trace(tmp_path / "logs")
    trace.start()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: sse("keep")))
    play = Play(cfg, Link(), trace, client, lambda: [], lambda t: t)
    learned = []
    play.on_learned = learned.append
    play.on_state(state())
    play.runner.start("follow", {})
    before = play.runner.current
    path.write_text(SKILLS.replace("k.follow()", "k.stay()"))
    os.utime(path, (time.time() + 5, time.time() + 5))
    subprocess.run([*commit, "I hold where I am instead of following (s-002)"], check=True)
    play.on_state(state())
    assert play.runner.current is not before and "k.stay()" in play.runner.current.skill.code
    assert learned == ["I hold where I am instead of following"]
    await asyncio.sleep(0)
    await client.aclose()
    await trace.close()
