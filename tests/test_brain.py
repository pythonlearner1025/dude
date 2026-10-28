import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

import m8py.brain as brainmod
from m8py.brain import Brain, Event, Heard, Memory, Summary, joint_options
from m8py.speak import EndJob, SentenceJob
from m8py.speaking import Speaking
from m8py.trace import Trace


class Link:
    def __init__(self):
        self.state = {
            "type": "state",
            "player_name": "John",
            "game": "Halo",
            "level": "a10",
            "state": "Kevin is ready",
            "in_combat": True,
            "on_radio": False,
            "actions": [],
        }
        self.speech_cooldown = 5.0
        self.sent = []

    async def send_json(self, x):
        self.sent.append(x)

    async def view(self, timeout=2):
        return None


def make(cfg, tmp_path, handler=None):
    link = Link()
    trace = Trace(tmp_path / "logs")
    trace.start()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler or (lambda r: httpx.Response(200, json={})))
    )
    b = Brain(cfg, link, asyncio.Queue(), Speaking(), trace, asyncio.Queue(), client)
    return b, link, trace, client


@pytest.mark.asyncio
async def test_prompt_window_situation_and_messages(cfg, tmp_path):
    b, _, trace, client = make(cfg, tmp_path)
    b.memory.summary = "saved facts"
    b.memory.feed = [f"event {i}" for i in range(22)] + [
        "Kevin: Old answer",
        "John: newest question",
    ]
    prompt = b.prompt()
    assert "event 0" not in prompt and "event 4" in prompt
    assert (
        prompt.index("Kevin: Old answer")
        < prompt.index("Combat now.")
        < prompt.index("John: newest question")
    )
    messages = b.messages()
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].startswith("You are Kevin beside John in Halo.")
    assert "Never narrate or describe his actions" in messages[0]["content"]
    assert messages[-1]["role"] == "user" and messages[-1]["content"].endswith(
        "John: newest question"
    )
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert assistant[-1]["content"] == "Old answer"
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
async def test_role_merging(cfg, tmp_path):
    b, _, trace, client = make(cfg, tmp_path)
    b.link.state["in_combat"] = False
    b.memory.feed = ["John: one", "event two", "Kevin: yes", "Kevin: again", "event three"]
    m = b.messages()
    assert any(x["role"] == "user" and "John: one\nevent two" in x["content"] for x in m)
    assert any(x["role"] == "assistant" and x["content"] == "yes\nagain" for x in m)
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
async def test_decide_do_which_then_speak_and_player_skip(cfg, tmp_path, capsys):
    questions = []

    def handler(req):
        body = json.loads(req.content)
        questions.append(list(body["questions"]))
        if "which" in body["questions"]:
            ans = {
                "which": {"choice": next(iter(body["questions"]["which"]["criteria"]))}
            }
        else:
            choices = list(body["questions"]["do"]["criteria"])
            ans = {
                "do": {"choice": next(x for x in choices if x != "nothing")},
                "speak": {"noul": 0.7},
                "is_command": {"noul": 0.0},
            }
        return httpx.Response(200, json={"answers": ans, "timings": {"prompt_n": 1}})

    b, link, trace, client = make(cfg, tmp_path, handler)
    link.state["actions"] = [
        {
            "name": "shoot",
            "description": "shoots",
            "options": {"g": "grunt"},
            "then": [{"name": "reload", "description": "reloads"}],
        }
    ]
    span = trace.new_span("event")
    assert await b.decide(False, False, span) is True
    assert questions == [["do", "speak"], ["do"]]
    assert [x["action"] for x in link.sent] == ["shoot", "reload"]
    questions.clear()
    span = trace.new_span("heard")
    assert await b.decide(True, False, span) is True
    assert questions[0] == ["do", "speak", "is_command"]
    assert "[kev]" in capsys.readouterr().out
    await client.aclose()
    await trace.close()


def test_joint_options_inline_small_target_sets_only():
    actions = [
        {"name": "follow", "description": "follows Chief"},
        {"name": "shoot", "description": "shoots", "options": {"1": "grunt", "2": "elite"}},
        {
            "name": "many",
            "description": "chooses",
            "options": {str(i): f"target {i}" for i in range(9)},
        },
    ]
    criteria, decoded = joint_options("Kevin", actions)
    assert criteria["nothing"] == "Kevin carries on as he is"
    assert criteria["shoot: 2"] == "Kevin shoots: elite"
    assert decoded["shoot: 2"] == ("shoot", "2")
    assert "many: 0" not in criteria and decoded["many"] == ("many", None)


@pytest.mark.asyncio
async def test_cooldown_skips_speak(cfg, tmp_path):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, json={"answers": {"do": {"choice": "nothing"}}})

    b, _, trace, client = make(cfg, tmp_path, handler)
    assert await b.decide(False, True, trace.new_span("event")) is False
    assert len(calls) == 1
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["transport", "json", "spot"])
async def test_look_records_vision_failures_and_returns_fallback(cfg, tmp_path, failure):
    def handler(request):
        if failure == "transport":
            raise httpx.ConnectError("vision unavailable", request=request)
        if failure == "json":
            return httpx.Response(200, content=b"not json")
        content = json.dumps({"place": "door", "spot": "one"})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    b, link, trace, client = make(cfg, tmp_path, handler)
    link.view = lambda timeout=2: asyncio.sleep(
        0,
        result=SimpleNamespace(
            rgb=bytearray(b"\x00\x00\x00"),
            width=1,
            height=1,
            spots=[{"id": 1, "x": 0.5, "y": 0.5, "metres": 2}],
        ),
    )

    span = trace.new_span("event")
    what, picture = await b.look("choose", {"type": "action"}, span)

    sight = trace.entries[-1]
    assert what == "he can't see it"
    assert picture and sight["kind"] == "sight"
    assert sight["data"]["picture"] == picture
    assert sight["data"]["error"]
    assert span.data["error_stage"] == "vision"
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["transport", "status"])
async def test_say_failure_before_stream_does_not_add_feed_or_open_line(cfg, tmp_path, failure):
    def handler(request):
        if failure == "transport":
            raise httpx.ConnectError("llm unavailable", request=request)
        return httpx.Response(503)

    b, _, trace, client = make(cfg, tmp_path, handler)
    before = b.memory.feed.copy()

    await b.say(trace.new_span("heard"))

    assert b.memory.feed == before
    assert b.speaking.lines == 0
    assert b.speech.empty()
    assert trace.entries[-1]["data"]["error"]
    assert trace._spans[next(iter(trace._spans))].data["error_stage"] == "llm"
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
async def test_respond_finishes_span_when_kev_fails(cfg, tmp_path):
    def handler(request):
        return httpx.Response(503)

    b, _, trace, client = make(cfg, tmp_path, handler)
    span = trace.new_span("heard")

    with pytest.raises(httpx.HTTPStatusError):
        await b.respond(True, span)

    assert span.data["error_stage"] == "kev"
    assert span._finished
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
async def test_say_accepts_usage_chunk_without_choices(cfg, tmp_path, capsys):
    usage = {"prompt_tokens": 3, "completion_tokens": 2}
    timings = {"prompt_ms": 4, "predicted_ms": 5}
    chunks = [
        {"model": "mock", "choices": [{"delta": {"content": "Hello."}}]},
        {"choices": [], "usage": usage, "timings": timings},
        {"usage": usage, "timings": timings},
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"

    def handler(request):
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    b, _, trace, client = make(cfg, tmp_path, handler)
    span = trace.new_span("heard")

    await b.say(span)

    assert span.data["llm_usage"] == usage
    assert span.data["llm_timings"] == timings
    assert b.memory.feed[-1] == "Kevin: Hello."
    assert isinstance(await b.speech.get(), SentenceJob)
    assert isinstance(await b.speech.get(), EndJob)
    assert "[llm]" in capsys.readouterr().out
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
async def test_voice_cancels_and_resumes_reflect(cfg, tmp_path):
    reflect_started = asyncio.Event()
    reflect_calls = 0

    async def handler(request):
        nonlocal reflect_calls
        body = json.loads(request.content)
        if body.get("id_slot") == 1:
            reflect_calls += 1
            if reflect_calls == 1:
                reflect_started.set()
                await asyncio.Event().wait()
            content = json.dumps({"orders": ["Stay close"], "remember": ["John trusts Kevin"]})
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        stream = (
            'data: {"choices":[{"delta":{"content":"Copy."}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})

    b, _, trace, client = make(cfg, tmp_path, handler)
    b._request_reflect("test command")
    await reflect_started.wait()

    await b.say(trace.new_span("heard"))
    await b.reflect_task

    entries = [entry["data"] for entry in trace.entries if entry["kind"] == "reflect"]
    assert reflect_calls == 2
    assert [entry["interrupted"] for entry in entries] == [True, False]
    assert b.memory.orders == ["Stay close"]
    assert b.memory.remember == ["John trusts Kevin"]
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
async def test_fold_over_arithmetic(cfg, tmp_path):
    b, _, trace, client = make(cfg, tmp_path)
    b.memory.feed = ["x" * 4000] * 21
    assert b.feed_tokens(b.memory.feed) == 21005
    before = asyncio.all_tasks()
    b.fold_over(20000)
    assert b.summarizing
    created = asyncio.all_tasks() - before
    for task in created:
        task.cancel()
    await asyncio.gather(*created, return_exceptions=True)
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
async def test_saves_loaded_and_generation_guard(cfg, tmp_path):
    b, link, trace, client = make(cfg, tmp_path)
    b.memory = Memory("old", ["a"])
    await b.on_saved("s1")
    b.memory.feed.append("b")
    await b.on_loaded("s1")
    assert b.memory.feed == ["a"]
    before = b.memory.summary
    b.on_summary(Summary(b.memory_generation - 1, 1, "wrong"))
    assert b.memory.summary == before
    await b.on_loaded("unknown")
    assert b.memory.feed == [] and b.memory.summary == ""
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
async def test_new_game_clears_all_memory_saves_and_speech(cfg, tmp_path):
    b, link, trace, client = make(cfg, tmp_path)
    b.memory = Memory("old summary", ["old feed"])
    await b.on_saved("a10:30")
    b.memory.feed.append("after checkpoint")
    b.summarizing = True
    old_generation = b.memory_generation
    b.speaking.begin_line()

    await b.on_new_game("b30")

    assert b.memory == Memory()
    assert b.saves == []
    assert json.loads(b.saves_path.read_text()) == []
    assert b.memory_generation == old_generation + 1
    assert not b.summarizing
    assert b.speaking.generation == 1
    assert link.sent[-1] == {"type": "stop_audio"}
    assert trace.entries[-1]["data"]["text"] == "(new game: b30, memory reset)"

    b.on_summary(Summary(old_generation, 1, "stale"))
    assert b.memory == Memory()
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
async def test_event_batching_holds_non_event(cfg, tmp_path, monkeypatch):
    b, _, trace, client = make(cfg, tmp_path)
    seen = []

    async def events(items, quiet=False):
        seen.append([x.text for x in items])

    async def heard(item):
        seen.append(item.text)
        raise asyncio.CancelledError

    b.on_events = events
    b.on_heard = heard
    await b.inputs.put(Event("a"))
    await b.inputs.put(Event("b"))
    await b.inputs.put(Heard("c"))
    task = asyncio.create_task(b.run())
    with pytest.raises(asyncio.CancelledError):
        await task
    assert seen == [["a", "b"], "c"]
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
async def test_quiet_event(cfg, tmp_path, monkeypatch):
    b, _, trace, client = make(cfg, tmp_path)
    b.link.state["in_combat"] = False
    b._last_input = time.monotonic() - 5
    monkeypatch.setattr(brainmod, "QUIET", 0.01)
    seen = []

    async def events(items, quiet=False):
        seen.append((items[0].text, quiet))
        raise asyncio.CancelledError

    b.on_events = events
    task = asyncio.create_task(b.run())
    with pytest.raises(asyncio.CancelledError):
        await task
    assert seen == [(brainmod.QUIET_EVENT, True)]
    await client.aclose()
    await trace.close()
