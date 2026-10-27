# Plan: m8 on b650s, then a general companion architecture

## Objectives
1. Run m8's architecture standalone on b650s (RTX 3090 Ti 24 GB), reimplemented in Python
   (`m8py`), and play Halo CE with it, streamed to a MacBook (Sunshine/Moonlight over Tailscale,
   mic via `clients/mic_client.py`). If the stack doesn't fit in VRAM: Gemma4-12B → Qwen3.5-9B
   uncensored (HauhauCS), then further reductions.
2. Log everything (module outputs, latency per stage, VRAM per server) and use the findings to
   design a general architecture + training infra for companions in any game (Minecraft and Rust
   first).

## Machine
b650s = Tailscale `minjune-650s`: Ubuntu 22.04, Ryzen 7 7700X, 30 GB RAM, RTX 3090 Ti (23 028
MiB), CUDA 12.8, driver 580, ~114 GB free disk. Workspace `~/m8work` (reference m8, llama.cpp,
models, breeze-tts, halo, dude = this repo, logs, codex-out). Codex CLI logged in there.

## VRAM budget (estimates, to be replaced by measurements in `gpu.jsonl`)

| Component | As m8 ran it (5090) | b650s plan A | Plan B (reductions) |
| --- | --- | --- | --- |
| Kev-4B | Q8_0 4.5 GB, 32k ctx | Q8_0, 8k ctx (Kev reads ≤20 feed lines) ≈ 5.0 GB | Q4_K_M ≈ 3.4 GB |
| Talk/see LLM | Gemma4-12B Q4_K_M 7.4 + mmproj 0.2, 32k q8 KV | same, 24k ctx ≈ 10-11 GB | Qwen3.5-9B Q4_K_M 5.6 + mmproj 0.9 (hybrid attn, small KV) ≈ 7.5 GB |
| Breeze TTS 2 (3B) | per-stage CUDA graphs | same ≈ 8-10 GB | eager ≈ 7.7 GiB |
| Parakeet STT | CPU | CPU | CPU |
| Halo (OpenCE) + Sunshine NVENC | — | ≈ 1 GB | ≈ 1 GB |
| **Total** | ~25 GB | **≈ 24-27 GB (likely over)** | **≈ 19.5 GB** |

Expectation: plan A is marginal; first measured run decides. Order of reductions if over:
Kev ctx → Kev Q4_K_M → LLM ctx 16k → Breeze eager → Qwen3.5-9B.

## Workstreams (Codex subagents on b650s; Claude plans and reviews)
- A. Model servers: llama.cpp (with `/v1/systemone`), model downloads, Breeze TTS, scripts.
- B. OpenCE Halo native Linux build with m8's patch; game-data path; exact protocol notes.
- C. `m8py` port per `docs/port-spec.md` (tracing, fake game, mocks, remote mic, tests).
- D. Bring-up: measure VRAM, fit, fake-game benchmarks, then real playtests (needs game data).
- E. Findings → general architecture + training infra brainstorm (`docs/general-architecture.md`).

## Status
See commits and `docs/findings.md` (created once measurements exist).

## Open items owned by the user
- Halo CE game data: OpenCE needs an Xbox disc image of a copy you own.
- Tailscale: the auth key used for this session was pasted in chat; revoke it in the admin
  console once you have a reusable/ephemeral key in the environment's secrets.
