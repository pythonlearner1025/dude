from pathlib import Path

from m8py.config import Config


def test_b650_llm_temperature_matches_rust_config():
    path = Path(__file__).parents[1] / "configs" / "b650s.toml"
    assert Config.load(path).llm.temperature == 1.0
