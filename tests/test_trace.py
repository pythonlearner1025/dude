import json

import pytest

from m8py.trace import Trace


@pytest.mark.asyncio
async def test_trace_span_and_report(tmp_path):
    t = Trace(tmp_path, "123")
    t.start()
    t.add("heard", {"text": "hi"})
    s = t.new_span("heard", vad_speech_end=10)
    s.set(spoke=True, action="nothing")
    s.mark("first_audio_sent")
    s.finish()
    await t.close()
    assert json.loads((t.session_dir / "trace.jsonl").read_text())["kind"] == "heard"
    span = json.loads((t.session_dir / "spans.jsonl").read_text())
    assert "mouth_to_ear_ms" in span
    assert "Turns: 1" in (t.session_dir / "summary.md").read_text()
