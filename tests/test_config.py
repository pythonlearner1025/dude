from pathlib import Path

from m8py.config import Config


def test_b650_llm_temperature_matches_rust_config():
    path = Path(__file__).parents[1] / "configs" / "b650s.toml"
    assert Config.load(path).llm.temperature == 1.0


def test_coop_config_has_no_kev_and_launches_kevin():
    cfg = Config.load(Path(__file__).parents[1] / "configs" / "b650s-coop.toml")
    assert cfg.kev is None
    assert cfg.p2p.instruction.name == "p2p-instruction.txt"
    assert cfg.p2p.launch.name == "kevin-coop.sh"
