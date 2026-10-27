import json
import time

import pytest

from m8py.trace import Trace, process_label


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


@pytest.mark.asyncio
async def test_span_finishes_once_and_report_counts_error_stage(tmp_path):
    t = Trace(tmp_path, "errors")
    t.start()
    span = t.new_span("heard")
    span.set_error("kev", "offline")
    span.finish()
    span.finish()
    await t.close()

    records = (t.session_dir / "spans.jsonl").read_text().splitlines()
    assert len(records) == 1
    assert json.loads(records[0])["error_stage"] == "kev"
    assert "Errors by stage: {'kev': 1}" in (t.session_dir / "summary.md").read_text()


@pytest.mark.asyncio
async def test_absolute_input_clock_includes_queue_wait_in_latency(tmp_path):
    t = Trace(tmp_path, "clock")
    t.start()
    now = time.monotonic()
    heard = t.new_span(
        "heard",
        vad_speech_start_at=now - 0.4,
        vad_speech_end_at=now - 0.3,
        stt_done_at=now - 0.2,
    )
    heard.data["first_audio_sent"] = 50
    heard.finish()
    event = t.new_span("event", event_received_at=now - 0.5)
    event.data["first_audio_sent"] = 25
    event.finish()
    await t.close()

    assert heard.data["vad_speech_end"] < 0
    assert heard.data["queue_wait_ms"] == pytest.approx(200, abs=5)
    assert heard.data["mouth_to_ear_ms"] == pytest.approx(350, abs=5)
    assert event.data["event_to_ear_ms"] == pytest.approx(525, abs=5)
    report = (t.session_dir / "summary.md").read_text()
    assert report.index("## Key metrics") < report.index("## Latencies")
    assert "| mouth_to_ear_ms |" in report
    assert "| queue_wait_ms |" in report


def test_gpu_process_labels_distinguish_models_and_python(tmp_path):
    llama = tmp_path / "101"
    llama.mkdir()
    (llama / "cmdline").write_bytes(
        b"/opt/llama-server\0--model\0/models/chat.gguf\0--port\08081\0"
    )
    python = tmp_path / "102"
    python.mkdir()
    (python / "cmdline").write_bytes(b"python3\0-m\0m8py.mocks\0")

    assert process_label(101, tmp_path) == "chat.gguf:8081"
    assert process_label(102, tmp_path) == "m8py.mocks"
