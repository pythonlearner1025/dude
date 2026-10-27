# m8 model infrastructure report

Generated 2026-10-27 on the Ubuntu 22.04 host described in the task. No GPU inference was started. The sole inference smoke test used `-ngl 0`; the pre-existing root-owned vLLM process was never signalled or modified.

## 1. Components

| Component | Status | Path | Version / revision | Size on disk |
| --- | --- | --- | --- | ---: |
| llama.cpp source + CUDA build | **ok** | `/home/minjune/m8work/llama.cpp` (`build/bin/llama-server`, `build/bin/llama-cli`) | `0.7.0-dev`, **b11945**, commit `d05706b4f32a545814856e98ca518292585443b9`; Release, `GGML_CUDA=ON`, CUDA arch `86` only | 894M |
| `/v1/systemone` route | **ok** | `llama.cpp/tools/server/server.cpp` and `server-context.cpp` | Route is present in current master and exercised successfully below | included above |
| Hugging Face CLI | **ok** | `/home/minjune/.local/bin/hf` → uv tool environment | `huggingface_hub` / `hf` 2.3.0; repaired shebang. No HF token is configured, and none was needed for these public repositories | 26M |
| Kev-4B Q8_0 + Q4_K_M | **ok** | `/home/minjune/m8work/models/kev-4b` | HF revision `f4624b6bb7072f1bab726a622c1cad3f96030b9e`; exact files `Kev-4B-Q8_0.gguf` and `Kev-4B-Q4_K_M.gguf` | 7.1G |
| Gemma 4 12B HauhauCS + vision projector | **ok** | `/home/minjune/m8work/models/gemma-4-12b-hauhaucs` | HF revision `ae8045ac2bd216293ca49a3065da2c942dde4b68`; requested Q4_K_M and BF16 mmproj filenames | 7.1G |
| Qwen3.5 9B HauhauCS fallback + vision projector | **ok** | `/home/minjune/m8work/models/qwen3.5-9b-hauhaucs` | HF revision `0a41c68809d375475f954be12ba7c40efa56c2a9`; requested Q4_K_M and BF16 mmproj filenames | 6.1G |
| Breeze TTS 2 checkpoint | **ok** | `/home/minjune/m8work/models/breeze-tts-2` | Whole public repo, HF revision `3e28c5151381a722f1d8661b4118c298caa77aa4`; not gated | 7.2G |
| Breeze TTS server + venv | **ok** | `/home/minjune/m8work/breeze-tts` | Upstream `6eba901d1845353802652c708a4740fdfc5baa75`; reference-cache patch applied as `1c4b9a397fc74d0adb90a1cfb5f8768942789019`; Python 3.11.14, Torch 2.9.1+cu128, FlashAttention 2.8.3 built for sm_86 only | 7.8G |
| Silero VAD | **ok** | `/home/minjune/m8work/models/silero_vad.onnx` | sherpa-onnx `asr-models` release asset | 632K |
| Parakeet TDT 0.6B v2 int8 | **ok** | `/home/minjune/m8work/models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8` | sherpa-onnx `asr-models` release; archive unpacked and deleted | 631M |
| STT server target supplied by the separate agent | **ok** | `/home/minjune/m8work/dude`, module `m8py.stt_server` | Git commit `269c6454df030c6ecc9ddb09e98ca382c013deed`; its CLI accepts `model_dir [port]` and binds `127.0.0.1` | 145M |
| Launch/stop scripts | **ok** | `/home/minjune/m8work/scripts` | Bash syntax checked; requested scripts executable; PID identity includes Linux process start time to avoid signalling a recycled PID | about 32K for the requested files |

The official FlashAttention 2.8.3 release has no CPython 3.11 wheel compatible with Torch 2.9.1. The permitted source build was therefore used with `MAX_JOBS=6` and `FLASH_ATTN_CUDA_ARCHS=86`; it completed in 19m54s. Both required checks pass:

```text
breeze_infer import: ok
flash_attn 2.8.3
torch 2.9.1+cu128
```

`python -m breeze_infer.api --help` also exits successfully and lists all expected fast-path flags.

## 2. CPU-only SystemOne smoke test

Server command used the requested Q8 model with `-ngl 0 -c 2048 --cache-ram 0`, bound only to `127.0.0.1:8080`. Exactly one inference request was sent, after which the server was stopped.

Request:

```json
{"model":"kev-latest","state":"Kevin is a soldier. A grunt is shooting at Kevin.","questions":{"do":{"type":"choice","instructions":"Which of these does Kevin do now?","criteria":{"nothing":"Kevin carries on as he is","shoot":"Kevin shoots at an enemy","follow":"Kevin follows Chasm"}},"speak":{"type":"noul","instructions":"Should Kevin speak now?"}}}
```

Exact response body:

```json
{"model":"/home/minjune/m8work/models/kev-4b/Kev-4B-Q8_0.gguf","answers":{"do":{"type":"choice","choice":"shoot","probabilities":{"nothing":0.1715745121709343,"shoot":0.8048177762421789,"follow":0.02360771158688682},"confidence":0.7072266643632683},"speak":{"type":"noul","noul":0.11454020897194407}},"usage":{"input_tokens":76,"output_tokens":0}}
```

Version check:

```text
version: 0.7.0-dev (build 11945, commit d05706b4f)
built with GNU 11.4.0 for Linux x86_64
```

## 3. Breeze TTS notes

- CLI: positional `model`, plus `--revision`, `--host`, `--port`, and Boolean pairs `--[no-]fast-all`, `--[no-]fast-text-encoder`, `--[no-]fast-backbone-prefill`, `--[no-]fast-backbone-decode`, `--[no-]fast-depth-decoder`, and `--[no-]fast-codec`.
- `--fast-all` enables the CUDA-graph fast path for all five stages. The m8 launch script enables only backbone decode, depth decoder, and codec. `BREEZE_MODE=eager` removes all fast flags.
- Published VRAM figures: approximately 7.7 GiB eager and 14.4 GiB with `--fast-all`; the README recommends at least 12 GB for eager and 24 GB for the full fast path. It does not publish an exact figure for m8's three-flag mix.
- During load, `GET /health` returns HTTP 503 with `{"status":"loading"}`. When ready it returns HTTP 200 with `{"status":"ok","sample_rate":24000}` for this checkpoint/runtime; the implementation obtains `sample_rate` from the loaded runtime, which satisfies m8.
- `POST /v1/audio/speech` multipart form fields: required `text`; optional `instruction`; `cfg_scale` (default `1.0`); `ref_audio`; `ref_text` (default empty); and `seed` (default `42`). `ref_audio` and non-empty `ref_text` must be supplied together.
- Successful speech output is streaming mono 24 kHz signed 16-bit little-endian PCM (`audio/pcm`), with `X-Sample-Rate` and `X-Sample-Format: s16le` headers.
- The service is single-concurrency. A streaming or batch request while the inference slot is occupied returns HTTP 409 with `{"detail":"An inference request is already running."}`.
- The applied m8 patch caches encoded reference audio by SHA-256 of its contents.
- License note: the source is Apache-2.0, but the downloaded model weights and self-hosted outputs are research/non-commercial under the BreezeBlue model license.

## 4. Scripts and use

All services bind `127.0.0.1`, write logs under `/home/minjune/m8work/logs`, and store PID plus process-start identity under `/home/minjune/m8work/run`.

| Script | Purpose and defaults |
| --- | --- |
| `scripts/start-kev.sh` | Kev Q8_0, port 8080, context 8192. Set `KEV_QUANT=Q4_K_M` for the smaller quant; `KEV_CTX` and `KEV_PORT` override defaults. |
| `scripts/start-chat.sh` | Gemma 12B + mmproj, port 8081, context 32768, m8's requested sampling and cache flags. `CHAT_CTX`/`CHAT_PORT` override defaults. |
| `scripts/start-chat-qwen.sh` | Qwen fallback + mmproj on port 8081. Non-thinking model-card sampling: temperature 0.7, top-k 20, top-p 0.8, min-p 0; reasoning off. |
| `scripts/start-breeze.sh` | Breeze on port 7860 with `--fast-backbone-decode --fast-depth-decoder --fast-codec`. Use `BREEZE_MODE=eager` for no fast flags. |
| `scripts/start-stt.sh` | Runs `python -m m8py.stt_server <parakeet-dir> 8083` from `dude`; uses its venv when present. |
| `scripts/stop-all.sh` | Sends SIGTERM only to live, identity-matched PIDs recorded for Kev, Gemma/Qwen chat, Breeze, and STT. Stale/recycled PID records are not signalled. |

Examples:

```bash
cd /home/minjune/m8work
./scripts/start-kev.sh
./scripts/start-chat.sh                 # or ./scripts/start-chat-qwen.sh
./scripts/start-breeze.sh               # BREEZE_MODE=eager ./scripts/start-breeze.sh
./scripts/start-stt.sh
./scripts/stop-all.sh
```

Do not run Gemma and Qwen simultaneously on their shared default port. `LLAMA_SERVER`, `BREEZE_PYTHON`, `BREEZE_MODEL`, `STT_PYTHON`, `DUDE_DIR`, and `PARAKEET_MODEL` provide path overrides.

## 5. Blockers and required user action

There are **no installation or download blockers**. Breeze was public and did not require license acceptance or an HF token. No token was created or requested.

Runtime GPU startup was intentionally not tested because the task prohibited any GPU inference. Before launching, the user should verify that enough VRAM is free; on this 24 GB card, use `start-chat-qwen.sh` and/or `BREEZE_MODE=eager` if the preferred simultaneous stack does not fit.

For commercial use, the self-hosted Breeze checkpoint is not licensed for that purpose. The user must obtain appropriate commercial rights or use BreezeBlue's separately licensed hosted service; no license action was taken here.

## 6. Disk use

- Requested infrastructure directories (`llama.cpp`, `breeze-tts`, `models`, and `scripts`): **39,178,399,744 allocated bytes**, approximately **36.5 GiB** (`du -sh` rounds the aggregate to 38G).
- Entire `/home/minjune/m8work` at handoff, including the pre-existing/reference checkout and the separate agent's work: **38G**.
- Filesystem free at handoff: **74G**.
- No `.incomplete`, `.aria2`, or Parakeet `.tar.bz2` files remain under `models`.

This job remained below the requested 50 GB footprint cap.
