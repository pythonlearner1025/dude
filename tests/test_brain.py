import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

import m8py.brain as brainmod
from m8py.brain import Brain, Event, Heard, Memory, Summary
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
    assert messages[0] == {"role": "system", "content": "You are Kevin beside John in Halo."}
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
async def test_decide_do_which_then_speak_and_player_skip(cfg, tmp_path):
    purposes = []

    def handler(req):
        body = json.loads(req.content)
        key = next(iter(body["questions"]))
        purposes.append(key)
        if key == "speak":
            ans = {"speak": {"noul": 0.7}}
        elif key == "which":
            ans = {"which": {"choice": next(iter(body["questions"][key]["criteria"]))}}
        else:
            choices = list(body["questions"][key]["criteria"])
            ans = {"do": {"choice": next(x for x in choices if x != "nothing")}}
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
    assert purposes == ["do", "which", "do", "speak"]
    assert [x["action"] for x in link.sent] == ["shoot", "reload"]
    purposes.clear()
    span = trace.new_span("heard")
    assert await b.decide(True, False, span) is True
    assert "speak" not in purposes
    await client.aclose()
    await trace.close()


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

    what, picture = await b.look("choose", {"type": "action"}, trace.new_span("event"))

    sight = trace.entries[-1]
    assert what == "he can't see it"
    assert picture and sight["kind"] == "sight"
    assert sight["data"]["picture"] == picture
    assert sight["data"]["error"]
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
    await client.aclose()
    await trace.close()


@pytest.mark.asyncio
async def test_say_accepts_usage_chunk_without_choices(cfg, tmp_path):
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
