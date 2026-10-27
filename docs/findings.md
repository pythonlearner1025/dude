# Findings: m8 architecture on one RTX 3090 Ti (b650s)

Living log of measurements. Numbers are from b650s (RTX 3090 Ti 23 028 MiB, Ryzen 7 7700X),
llama.cpp b11945 (CUDA, sm_86), Breeze TTS 2 @ 6eba901 + m8's reference-cache patch.

## 1. VRAM: m8's stack as shipped does not fit in 24 GB

Measured per process with `nvidia-smi --query-compute-apps` after each server reported healthy.

| Component | Config | VRAM (MiB) |
| --- | --- | ---: |
| Xorg + Sunshine (idle, for Moonlight streaming) | 1080p60, NVENC | 277 |
| Kev-4B Q8_0 (decide) | `-c 8192` (m8 used 32768), 4 slots | 5 420 |
| Kev-4B Q8_0 | `-c 4096 -np 1` | 5 198 |
| Gemma4-12B QAT Q4_K_M + mmproj (talk/see) | `-c 32768`, q8 KV, 4 slots (m8's flags) | 8 886 |
| Qwen3.5-9B Q4_K_M + mmproj (talk/see, fallback) | `-c 32768`, q8 KV, 4 slots | 7 216 |
| Qwen3.5-9B Q4_K_M + mmproj | `-c 32768 -np 2` | 7 100 |
| Breeze TTS 2 (speak) | m8's flags: `--fast-backbone-decode --fast-depth-decoder --fast-codec` | 9 000 |
| Parakeet TDT 0.6B int8 (hear) | CPU (sherpa-onnx) | 0 |

- **m8 as shipped (Kev + Gemma 12B + Breeze fast path):** Breeze OOMs while capturing its
  backbone CUDA graph with Kev (5.3 GiB) and Gemma (8.7 GiB) resident: needs ≈ 23.6 GB + game.
- **Fitted stack (Kev Q8 4k/1 slot + Qwen3.5-9B 32k/2 slots + Breeze m8 flags + X/Sunshine):
  21 643 / 23 028 MiB**, leaving ~1.35 GB for the game (OpenCE Halo, 32-bit GL 4.5) and the live
  NVENC session. Context/slot trimming only saved ~340 MB; the real lever was the 12B → 9B swap
  (−1.7 GB). Next levers if needed: Kev Q4_K_M (≈ −1.4 GB), Breeze eager (no CUDA graphs).
- Breeze is the single largest consumer (9.0 GB for a 3B TTS) — more than the 9B LLM.
  Every model also pays its own CUDA context (~0.3-0.5 GB per process).

## 2. Per-server latency in isolation (fitted stack, warm)

`tools/microbench.py` on b650s; m8-shaped prompts (Kevin persona, level a30 story, 19 feed lines,
"Right now" state, 11 actions).

| Call | Latency | Notes |
| --- | --- | --- |
| Kev `do` (11-way choice), ~830 prompt tokens | cold 356 ms, warm p50 **141 ms** | Kev re-reads its whole prompt every call (`--cache-ram 0`, no prefix reuse for decision models) |
| Kev `speak` (noul) | p50 **122 ms** | |
| Qwen3.5-9B stream, ~730 prompt tokens | first token 220 ms cold → **41-44 ms** with prefix cache | 120 tok/s generation; `cache_n` 726/730 on repeat |
| Qwen3.5-9B vision `describe`, 1920×1080 PNG | **2 027 ms** | on the critical path of `look`/`go_to` actions |

Implication for a spoken reply to the player (serial critical path): VAD end-of-speech (≥100 ms
silence) → STT → Kev `do` (~140 ms) [+ `which` ~120 ms] [+ `then` chain] → LLM first token
(~45 ms) → first complete sentence (a `[direction]` note + ~10-20 tokens ≈ 150-250 ms) → Breeze
first audio → game. Kev's serial calls are a large, avoidable slice (no KV reuse across the 2-5
calls of one turn, all with the same prefix).

## 3. Qualitative notes so far

- Qwen3.5-9B uncensored holds the Kevin persona well (crude, cocky, starts lines with a
  `[voice direction]`), but lines run longer than the persona's "a quick line or two".
- Kev on the 11-action prompt chose `shoot` with confidence 0.10 (probabilities spread across
  options); `speak` came out 0.54 — near the 0.5 threshold. Decisions near-uniform across many
  actions are worth tracking per turn (the trace keeps Kev's full probability vectors).
- Vision on a full 1080p frame costs ~2 s; downscaling the view before sending is an obvious
  latency win (to test).
