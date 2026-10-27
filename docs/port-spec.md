# m8py: Python port of m8 — implementation spec

Goal: a behaviour-faithful Python port of m8 (reference: `~/m8work/m8`, Rust, read every file
in `m8/src`) that runs on b650s (Linux, RTX 3090 Ti), plus the instrumentation we need to judge
the architecture. Read `docs/m8-architecture.md` first; where this spec and the Rust disagree on
behaviour, the Rust wins unless this spec explicitly says "change".

## Runtime and packaging

- Python 3.12 via `uv` (`uv sync`; `pyproject.toml`, package `m8py`, console script `m8py`).
- Deps (keep to these unless needed): `httpx` (async, streaming), `numpy`, `sherpa-onnx`
  (Silero VAD + Parakeet), `sounddevice` (local mic), `pillow` (PNG), `aiohttp` (site, STT
  server, remote-mic websocket), `pytest`, `pytest-asyncio`. `tomllib` for config.
- Single asyncio event loop. Blocking/CPU work (VAD, PNG encode, STT decode) via
  `asyncio.to_thread`. Mic capture callback thread → `loop.call_soon_threadsafe` into a queue.

## Modules (one per Rust file, same responsibilities)

| Module | Port of | Notes |
| --- | --- | --- |
| `m8py/config.py` | config.rs | Same `m8.toml` schema + new `[log]`, `[mic] source`, `[remote_mic]` sections. Paths relative to the config file. |
| `m8py/speaking.py` | `Speaking` in main.rs | until / generation / lines semantics exactly; monotonic clock. |
| `m8py/link.py` | link.rs | asyncio TCP server on `[game] port`; one active connection (new one replaces old); frame kinds 1-4; `state` replace; `settings`; `mic`; `view()` request with timeout (2 s) via Future; events/saved/loaded/direct → queue; kind-3 → hearing queue. Sends `hello` on connect. |
| `m8py/text.py` | SentenceSplitter, Notes, clean, SOUNDS | Exact semantics incl. unclosed-bracket and emoji ranges. Table-driven tests. |
| `m8py/brain.py` | brain.rs | Input types, loop (1 s poll, 45 s quiet event, event batching, held input), respond/decide/act/look/kev/say, prompt() and messages() construction byte-for-byte, fold_over/summary (as an asyncio task, generation-checked), saves.json (50 max), loaded restore. |
| `m8py/speak.py` | speak.rs | Breeze client (multipart incl. ref audio bytes, cfg 4 / 1, seed, 409 retry 20×100 ms), streaming s16le → kind-2 frames; stop_audio on generation takeover; audio_end; end_line. Pluggable `TTSBackend` interface (Breeze first). |
| `m8py/listen.py` | listen.rs | `Transcriber` (OpenAI-style multipart), `Listener` (resample → Silero 512 windows → margins 200/100 ms from 25 s ring → STT), barge-in, mute_while_speaking, game mute, save_recordings. Mic sources: `local` (sounddevice default input) and `remote` (see below). |
| `m8py/picture.py` | picture.rs | Same disc+digit marking (pixel-identical), PNG via Pillow, base64. |
| `m8py/trace.py` + `m8py/site.py` | site.rs + site.html + history.html | Same JSONL entry kinds and fields as Rust (`heard`, `event`, `kev`, `llm`, `sight`, `voice`, `summary`, `memory`); same HTTP endpoints so the ORIGINAL `site.html`/`history.html` (copy them from the reference, MIT) work unchanged on port 8090; editable prompt files. |
| `m8py/stt_server.py` | bin/stt-server.rs | Parakeet TDT int8 via sherpa-onnx python, `GET /health`, `POST /v1/audio/transcriptions` (multipart `file` or raw body WAV, resample to 16 k). `python -m m8py.stt_server <model_dir> [port]`. |
| `m8py/__main__.py` | main.rs | `m8py run [m8.toml]`, `--transcribe a.wav…`, `--simulate-mic a.wav…`; stdin lines → Heard; wires all tasks. Waits for each endpoint's `/health` (with a clear message) before starting. |

## New: instrumentation (the point of this experiment)

All in `logs/<session>/`:
1. `trace.jsonl` — the Rust trace entries, unchanged in shape (the history page reads it).
2. `spans.jsonl` — one record per *turn* (a Heard, an Event batch, or a quiet event), with
   `turn_id`, `trigger` (`heard|event|quiet`), monotonic timestamps (ms, relative to turn start)
   for every stage that happened: `vad_speech_start`, `vad_speech_end`, `stt_done`,
   `kev_do`, `kev_which`, `look_view_received`, `look_done`, `kev_then`, `kev_then_which`,
   `kev_speak`, `llm_request`, `llm_first_token`, `first_sentence`, `tts_request`,
   `tts_first_audio`, `first_audio_sent`, `llm_done`, `last_audio_sent`, plus `cut_off`,
   `spoke`, `action`, `option`, prompt token estimates (chars/4) for Kev and LLM, and the
   server-reported `timings` / `usage` from llama.cpp responses when present (prompt_n,
   predicted_n, prompt_ms, predicted_ms, cache_n). Key derived metric:
   `mouth_to_ear_ms = first_audio_sent - vad_speech_end` for heard turns,
   `event_to_ear_ms = first_audio_sent - turn start` for events.
3. `gpu.jsonl` — every 2 s: `nvidia-smi --query-gpu=memory.used,utilization.gpu` and per-process
   memory (`--query-compute-apps`), so we can attribute VRAM per server.
4. `audio/` — when `[log] save_audio = true`: every mic segment WAV and every TTS sentence WAV,
   named by turn_id.
5. On shutdown (and via `m8py report <session dir>`): `summary.md` with p50/p90/max per stage
   and per derived metric, counts of actions chosen, speak yes/no rate, cut-offs, errors.

Logging must never block the brain: buffered writer task.

## New: remote mic (player streams the game to a MacBook with Moonlight)

- `[mic] source = "remote"`: m8py serves `ws://0.0.0.0:<remote_mic.port>/mic` (default 8091,
  bind configurable, intended for the Tailscale interface). Client sends binary frames of
  16 kHz mono s16le (20 ms each) and optional JSON text frames (`{"type":"hello",...}`,
  `{"type":"ptt","down":bool}`); server feeds them to the same `Listener`.
- `clients/mic_client.py`: standalone script (deps: `sounddevice`, `websockets`, `numpy`) for
  the Mac: picks input device (`--list`, `--device`), resamples to 16 k, streams, reconnects;
  prints input level so the user can check it works. Document in README.

## New: fake game + mock models (for GPU-less tests and repeatable benchmarks)

- `m8py/fakegame.py`: a TCP client of the protocol that plays a scripted Halo-like scenario
  (JSON scenario files in `scenarios/`): sends `state` at 10 Hz with realistic `state` text and
  `actions` (follow, stay, shoot with enemy options, search_weapons with result+then pick_up,
  look view=describe, go_to view=choose), `event`s on a timeline (incl. react=false lines),
  kind-3 dialogue clips (from WAV fixtures), answers `view` with a fixture image + spots,
  `saved`/`loaded`, `settings`, scripted player lines (sent as text via the site endpoint or
  as WAV through `--simulate-mic`). It records everything m8 sends (actions, say, audio bytes →
  WAV per line, stop_audio timing) to `logs/<session>/fakegame.jsonl`.
  Use the protocol reference in `~/m8work/codex-out/B-game-report.md` (if present) to match the
  real Halo mod's messages.
- `m8py/mocks.py`: mock systemone (deterministic choices, configurable latency), mock chat
  completions (SSE streaming with configurable token rate, json_schema answers), mock TTS
  (sine/silence s16le stream at 24 kHz with /health sample_rate), mock STT. One command starts
  all mocks on the real ports: `python -m m8py.mocks`.
- `m8py/bench.py`: `m8py bench --scenario scenarios/x.json --config m8.toml` runs fakegame
  against the live m8py and prints the summary.

## New: a voice without a recorded clip

m8 ships no voice clip. Add `m8py voice-design --description "<voice description>" --text
"<a few sentences>" --out voices/kevin.wav`: uses Breeze TTS 2's voice-design mode (instruction
only, no reference audio — check the breeze-tts API for the exact fields) to synthesise a 8-15 s
reference clip once, writes the WAV and its transcript `.txt` beside it. m8py then clones that
clip for every line exactly as m8 does.

## Tests (must pass with mocks only, no GPU)

- text: SentenceSplitter/Notes/clean parity cases (derive from reading the Rust carefully,
  include streaming across chunk boundaries, notes mid-sentence, sounds variants, emoji, quotes).
- link: framing round-trip for all 4 kinds, partial reads, reconnect replaces writer.
- brain: prompt() and messages() for hand-built feeds (newest-own-line split, role merging,
  20-line Kev window, situation placement); decide flow with mocked Kev (do → which → then →
  speak; cooldown logic; to_player skips speak); event batching; quiet event; fold_over
  arithmetic; saves/loaded; interrupt drops stale TTS jobs.
- picture: digit bitmaps and disc placement on a small image.
- e2e: mocks + fakegame scenario runs 30 s and produces spans with all expected stages.

## Config for b650s

`configs/b650s.toml`: ports as in the table in `docs/m8-architecture.md`, persona
`personas/kevin` (copy `examples/kevin` from the reference), voice reference path
`voices/soldier.wav` (the user supplies the clip; until then the TTS must fail with a clear
message, and mocks can stand in), `[mic] source = "remote"`.

## Out of scope for this pass

Behaviour changes to the brain (we first measure the original design), new models, the game
mod itself (separate task), Windows support.
