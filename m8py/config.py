from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class MateConfig:
    name: str
    voice_server: str
    voice_reference: Path
    voice_seed: int
    persona: Path | None = None


@dataclass(slots=True)
class MicConfig:
    vad: str = "silero"
    mute_while_speaking: bool = True
    barge_in: bool = True
    save_recordings: bool = False
    vad_threshold: float = 0.5
    end_of_speech_silence: float = 0.1
    source: str = "local"


@dataclass(slots=True)
class EndpointConfig:
    url: str
    model: str | None = None
    temperature: float = 0.7


@dataclass(slots=True)
class P2PConfig:
    """Co-op mode: Kevin is player 2 and Open-P2P plays him from `instruction`, which Reflect
    writes. `launch` is run with the host's invite link to start Kevin's game and Open-P2P."""

    instruction: Path
    launch: Path | None = None


@dataclass(slots=True)
class ActorConfig:
    """Skill mode: a fast hosted model (OpenRouter) picks Kevin's skills from `library`; tickets
    for the coach (a frontier model in Claude Code) go to `tickets`."""

    model: str
    library: Path
    tickets: Path
    url: str = "https://openrouter.ai/api/v1/chat/completions"
    provider: str | None = None
    key_env: str = "OPENROUTER_API_KEY"
    timeout: float = 5.0


@dataclass(slots=True)
class ModelsConfig:
    silero_vad: Path


@dataclass(slots=True)
class GameConfig:
    port: int = 47800
    bind: str = "127.0.0.1"


@dataclass(slots=True)
class SiteConfig:
    port: int = 8090
    bind: str = "127.0.0.1"


@dataclass(slots=True)
class RemoteMicConfig:
    port: int = 8091
    bind: str = "0.0.0.0"


@dataclass(slots=True)
class LogConfig:
    directory: Path = Path("logs")
    save_audio: bool = False
    gpu_interval: float = 2.0


@dataclass(slots=True)
class Config:
    mate: MateConfig
    mic: MicConfig
    stt: EndpointConfig
    llm: EndpointConfig
    models: ModelsConfig
    game: GameConfig
    kev: EndpointConfig | None = None  # none in co-op mode: Open-P2P plays Kevin
    p2p: P2PConfig | None = None
    actor: ActorConfig | None = None
    site: SiteConfig = field(default_factory=SiteConfig)
    remote_mic: RemoteMicConfig = field(default_factory=RemoteMicConfig)
    log: LogConfig = field(default_factory=LogConfig)
    base_dir: Path = Path(".")

    @property
    def persona_dir(self) -> Path:
        return self.mate.persona or self.base_dir

    @classmethod
    def load(cls, path: str | Path) -> Config:
        path = Path(path).resolve()
        raw = tomllib.loads(path.read_text())
        base = path.parent

        def resolved(value: str | Path) -> Path:
            p = Path(value)
            return p if p.is_absolute() else (base / p).resolve()

        mate = dict(raw["mate"])
        mate["voice_reference"] = resolved(mate["voice_reference"])
        if mate.get("persona") is not None:
            mate["persona"] = resolved(mate["persona"])
        models = dict(raw.get("models", {}))
        models["silero_vad"] = resolved(models.get("silero_vad", "silero_vad.onnx"))
        logging = dict(raw.get("log", {}))
        logging["directory"] = resolved(logging.get("directory", "logs"))
        actor = dict(raw["actor"]) if "actor" in raw else None
        if actor:
            actor["library"] = resolved(actor["library"])
            actor["tickets"] = resolved(actor["tickets"])
        p2p = dict(raw["p2p"]) if "p2p" in raw else None
        if p2p:
            p2p["instruction"] = resolved(p2p["instruction"])
            if p2p.get("launch") is not None:
                p2p["launch"] = resolved(p2p["launch"])
        return cls(
            mate=MateConfig(**mate),
            mic=MicConfig(**raw.get("mic", {})),
            stt=EndpointConfig(**raw["stt"]),
            kev=EndpointConfig(**raw["kev"]) if "kev" in raw else None,
            p2p=P2PConfig(**p2p) if p2p else None,
            actor=ActorConfig(**actor) if actor else None,
            llm=EndpointConfig(**raw["llm"]),
            models=ModelsConfig(**models),
            game=GameConfig(**raw.get("game", {})),
            site=SiteConfig(**raw.get("site", {})),
            remote_mic=RemoteMicConfig(**raw.get("remote_mic", {})),
            log=LogConfig(**logging),
            base_dir=base,
        )
