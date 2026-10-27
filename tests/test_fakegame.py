import asyncio
import json
import socket
from pathlib import Path

import pytest

from m8py.bench import run_benchmark
from m8py.fakegame import FakeGame, _compact, _frame, _subframe


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_protocol_payloads_are_compact_and_big_endian():
    payload = _compact({"type": "action", "action": "shoot", "option": "17"})
    framed = _frame(1, payload)
    assert framed[:5] == b"\x01\x00\x00\x00" + bytes([len(payload)])
    assert b" " not in payload
    hear = _subframe({"speaker": "Cortana", "radio": True}, b"\x00\x00")
    length = int.from_bytes(hear[:2], "big")
    assert json.loads(hear[2 : 2 + length]) == {"speaker": "Cortana", "radio": True}


@pytest.mark.asyncio
async def test_action_consequences_change_simulated_state(tmp_path):
    scenario = {
        "initial_state": {
            "state": (
                "Kevin: unhurt, shields full, holding an assault rifle (60 rounds loaded, "
                "spare ammo), no second weapon, 2 frag and 0 plasma grenades. {player}: close "
                "by ahead, unhurt, shields full. Enemies: grunt close (8 m) ahead, in sight, "
                "unhurt."
            ),
            "actions": [
                {"name": "follow", "description": "follows {player}"},
                {
                    "name": "shoot",
                    "description": "shoots at an enemy",
                    "options": {"17": "grunt close (8 m) ahead, in sight, unhurt"},
                },
            ],
        }
    }
    fake = FakeGame(scenario, tmp_path)
    fake.state = dict(scenario["initial_state"])
    await fake._consequence({"action": "follow"})
    assert "following {player}" in fake.state["state"]
    before = asyncio.all_tasks()
    await fake._consequence({"action": "shoot", "option": "17"})
    assert "shooting at the grunt" in fake.state["state"]
    created = asyncio.all_tasks() - before
    for task in created:
        task.cancel()


@pytest.mark.asyncio
async def test_smoke_e2e_with_mocks(tmp_path: Path):
    kev, llm, tts, stt, game, site, mic = [free_port() for _ in range(7)]
    root = Path(__file__).parents[1]
    config = tmp_path / "e2e.toml"
    config.write_text(
        f'''[mate]
name="Kevin"
persona="{root / "personas/kevin"}"
voice_server="http://127.0.0.1:{tts}"
voice_reference="{root / "voices/mock.wav"}"
voice_seed=42
[mic]
source="remote"
vad="energy"
barge_in=true
mute_while_speaking=true
end_of_speech_silence=0.1
[remote_mic]
bind="127.0.0.1"
port={mic}
[stt]
url="http://127.0.0.1:{stt}/v1/audio/transcriptions"
[kev]
url="http://127.0.0.1:{kev}/v1/systemone"
[llm]
url="http://127.0.0.1:{llm}/v1/chat/completions"
temperature=0.7
[models]
silero_vad="{tmp_path / "unused.onnx"}"
[game]
bind="127.0.0.1"
port={game}
[site]
bind="127.0.0.1"
port={site}
[log]
directory="{tmp_path / "logs"}"
save_audio=false
gpu_interval=100
'''
    )
    session, result = await run_benchmark(
        root / "scenarios/smoke.json", config, mocks=True, speed=12
    )

    assert result["passed"], result["invariant_violations"]
    assert result["turns"] >= 4
    spans = [json.loads(line) for line in (session / "spans.jsonl").read_text().splitlines()]
    stages = {key for span in spans for key in span}
    assert {"kev_start", "kev_done", "llm_request", "first_sentence"} <= stages
    assert {"tts_request", "tts_first_audio", "first_audio_sent"} <= stages
    assert any(span.get("trigger") == "heard" for span in spans)
    entries = [
        json.loads(line) for line in (session / "fakegame.jsonl").read_text().splitlines()
    ]
    received = [entry.get("message", {}).get("type") for entry in entries]
    assert {"hello", "action", "say", "heard", "audio_end"} <= set(received)
    assert (session / "bench.json").exists()
    assert (session / "summary.md").exists()
    assert list((session / "fakegame-audio").glob("*.wav"))
