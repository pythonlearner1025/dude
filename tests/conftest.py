from pathlib import Path

import pytest

from m8py.config import Config


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    persona = tmp_path / "persona"
    (persona / "levels").mkdir(parents=True)
    (persona / "system_prompt.txt").write_text("You are Kevin beside {player} in {game}.")
    (persona / "combat_prompt.txt").write_text("Combat now.")
    (persona / "radio_prompt.txt").write_text("On radio with {player}.")
    (persona / "levels" / "a10.txt").write_text("Story for {player}.")
    (tmp_path / "voice.wav").write_bytes(b"RIFFmock")
    (tmp_path / "voice.txt").write_text("reference")
    text = """[mate]\nname="Kevin"\npersona="persona"\nvoice_server="http://tts"\nvoice_reference="voice.wav"\nvoice_seed=42\n[mic]\nsource="none"\nmute_while_speaking=true\nvad_threshold=0.5\nend_of_speech_silence=0.1\n[stt]\nurl="http://stt/v1/audio/transcriptions"\n[kev]\nurl="http://kev/v1/systemone"\n[llm]\nurl="http://llm/v1/chat/completions"\ntemperature=0.7\n[models]\nsilero_vad="vad.onnx"\n[game]\nport=0\n[log]\ndirectory="logs"\n"""
    path = tmp_path / "m8.toml"
    path.write_text(text)
    return Config.load(path)
