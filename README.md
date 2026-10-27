# dude

Experiments with AI companions that co-op real games.

Current work: a Python reimplementation of [m8](https://github.com/chasmlol/m8) (`m8py`), run on a
single RTX 3090 Ti and played in Halo: Combat Evolved (OpenCE), with every module's output and
latency logged, as the basis for a general companion architecture.

- `docs/PLAN.md` — objectives, machine, VRAM budget, workstreams
- `docs/m8-architecture.md` — how m8 works, as the port's reference
- `docs/port-spec.md` — the spec for `m8py`

## m8py

Use Python 3.12 through `uv`:

```bash
uv sync
uv run python -m m8py.mocks
# in another terminal
uv run m8py run configs/mock.toml
```

The brain page is at `http://127.0.0.1:8090`; its Talk and Event boxes work even with no game
connected. The mock command provides deterministic Kev, chat/SSE, Breeze, and STT endpoints on
the production ports.

For real servers, start the four model endpoints separately and run:

```bash
uv run m8py run configs/b650s.toml
```

Supply `voices/soldier.wav` and its exact transcript `voices/soldier.txt`, plus the Silero ONNX
file configured under `[models]`. To create a reference voice without a recording:

```bash
uv run m8py voice-design --description "A rough, confident male soldier" \
  --text "Contact ahead. Stay low and keep moving." --out voices/kevin.wav
```

`configs/b650s.toml` accepts a remote microphone at `ws://HOST:8091/mic`. On the MacBook:

```bash
python clients/mic_client.py --list
python clients/mic_client.py --device 2 --url ws://B650S-TAILSCALE-IP:8091/mic
```

Each run writes Rust-compatible history plus `spans.jsonl`, GPU samples, optional WAVs, and
`summary.md` under `logs/<session>/`. Regenerate a report with:

```bash
uv run m8py report logs/<session>
```

Transcription utilities are available on `run`:

```bash
uv run m8py run configs/b650s.toml --transcribe clip.wav
uv run m8py run configs/b650s.toml --simulate-mic clip.wav
```
