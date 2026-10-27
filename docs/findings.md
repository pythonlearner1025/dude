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

## 3. End to end: fake game against the real models

`m8py bench` with the protocol-faithful fake game (`m8py/fakegame.py`, scenarios in
`scenarios/`) against the fitted stack. Small samples (2 sessions, 29 turns, 9 spoken replies);
the live Halo sessions will add more.

| Metric | p50 | p90 / max | n |
| --- | ---: | ---: | ---: |
| **Player speech end → first mate audio** (mouth-to-ear) | **0.78-0.91 s** | max 0.99 s | 4 |
| **Game event → first mate audio** | **1.07 s** | | 1 |
| STT (Parakeet int8, CPU) | 59-71 ms | 67 ms | 4 |
| Kev, whole decision chain | 276-372 ms | p90 505-899 ms; 2.06 s with a `look` (vision) | 25 |
| LLM request → first token | 162-166 ms | 288 ms | 9 |
| LLM request → first complete sentence | 351-419 ms | 488 ms | 9 |
| TTS request → first audio (Breeze) | 192 ms | 200 ms | 9 |
| LLM request → line fully written | 3.4-6.4 s | 6.8 s | 9 |
| Turn start → last audio sent | **13-18 s** | 22.7 s | 9 |
| Input queue wait | 0 ms | max 1.55 s (an event waiting behind a reply) | 29 |

- Kev's serial calls are ~40% of mouth-to-ear; the LLM's first sentence another ~40%
  (the `[voice direction]` note is generated before any speakable word).
- The first token is ~165 ms in a live turn vs ~45 ms in the isolated benchmark: each turn appends
  new feed lines before "Right now", so the prefix cache only covers the stable part.

## 4. Qualitative notes

- **Lines are far too long.** Replies were 79-159 words (mean ~115, 13-18 s of speech) against a
  persona that asks for "a quick line or two" and a combat prompt that asks for "a few words at a
  time". Length *grew* within a session (79 → 159 words): the model imitates its own previous
  long turns in the feed. The first live Halo line was ~80 words in 7 sentences.
- **Repetition:** 4 of 6 combat replies opened "[gritting teeth…] Fuck!"; melodrama escalates
  ("bleeding out like a stuck pig").
- **Ungrounded details:** invented injuries ("a plasma round to the shoulder") not in the state.
- **Directions vs actions:** m8 treats every `[...]` as a voice direction for the TTS, but the
  model also writes stage actions in brackets ("[shoves a fresh mag into the assault rifle]"),
  which reach Breeze as speaking instructions.
- Qwen3.5-9B uncensored otherwise holds Kevin's voice (crude, cocky, in-universe).
- Kev on the 11-action prompt chose `shoot` with confidence 0.10 (probabilities spread across
  options); `speak` came out 0.54 — near the 0.5 threshold. Kev's calibration was fit on
  documents/QA (model card), not game states.
- Speak rate in the fake-game runs: 9 of 29 turns spoke (31%); actions mostly `nothing`/`follow`.
- Vision on a full 1080p frame costs ~2 s; downscaling the view before sending is an obvious
  latency win (to test).
- An A/B worth running: m8's original Gemma4-12B with Kev Q4_K_M (≈ −1.4 GB) fits the same
  budget as Qwen-9B + Kev Q8 and may follow the brevity instructions better.

