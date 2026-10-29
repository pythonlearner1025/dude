# LLMs do everything: how fast, and what is the unit of action? (2026-10-29)

The question after Open-P2P: drop learned visuomotor policies and let LLMs play Kevin. A fast LLM
acts in the loop; a frontier LLM above it writes skills (code), manages memory, recovers from
errors and writes the fast model's prompt. How fast must the in-loop model be to feel like 20 fps,
and what should it emit: a primitive, a tool call, a sequence, or a whole skill?

## Short answer

- **The 20 fps feel comes from code, not from the LLM.** Halo ticks at 30 Hz (33 ms); aiming and
  moving belong to skills that run every tick. No surveyed system runs a ≥1B model per tick, and
  the benchmarks that give a frontier model one action per call at real-time speed collapse
  (ROAR: Gemini 3.1 Pro co-op score 0.78 turn-based, 0.13 at 250 ms steps, 0.04 at 40 ms).
- **The fast model's unit is one parameterised skill call** ("flank elite#2"), with short plans
  for multi-step orders, at 2-10 Hz plus on every event. That matches human reaction times
  (~160-300 ms) and is what the working real-time systems do (PUBG Ally, PORTAL, DPT-Agent; Lumine
  emits 200 ms action chunks instead).
- **Skills are written only by the frontier model, asynchronously**, tested on recorded states,
  then hot-swapped. The fast model never writes code in the loop.
- **Measured on the 3090 Ti:** a 2B model picks a skill in 49 ms (20/s) but chose right 62% of the
  time; a 4B in 101 ms (10/s), 75% right; Gemma-12B 307 ms (3/s), 81%. Output format matters as
  much as model size: a terse call is ~5 tokens, JSON ~28.

## Measurements (b650s, RTX 3090 Ti, llama.cpp, `tools/llm_loop_bench.py`)

A fixed system prompt with Kevin's skills and body API (cached), a new ~170-token game-state
snapshot per step, thinking off, output constrained by a grammar. Medians of 10 steps.

| Model (Q4) | primitive, terse | skill, terse | skill, JSON | 5-skill plan | write a skill | right skill (16 probes) |
|---|---|---|---|---|---|---|
| Qwen3.5-0.8B | 41 ms | 35 ms | 112 ms | 358 ms | 0.3 s | 19% |
| Qwen3.5-2B | 61 ms | 49 ms | 142 ms | 458 ms | 0.5 s | 62% |
| Qwen3.5-4B | 115 ms | 101 ms | 208 ms | 592 ms | 2.3 s | 75% |
| Gemma4-12B (Voice's server) | 338 ms | 307 ms | 661 ms | 1.45 s | 2.8 s | 81% |

- Reading the new state dominates a terse step (4B: 72 of 101 ms); fewer state tokens per step is
  the next lever.
- A screenshot instead of the text state: Gemma 854 ms per skill call (435 new prompt tokens).
- The probes are 16 situations with an obvious skill ("Hold your fire." → hold_fire, an enemy at
  1 m → melee); a floor for choice quality, not a measure of tactics.
- Network from b650s to every LLM provider's edge: 3-8 ms (TCP), ~22 ms TLS setup once per
  connection. Cloud latency is the provider's, not the network's.

## Cloud speeds (Artificial Analysis medians to 2026-10-29, TTFT includes network)

| Model / provider | Output tok/s | Time to first token | Fit |
|---|---|---|---|
| gpt-oss-120B on Cerebras | ~1,800 | 0.22 s (1k prompt) | tactical layer at ~4 Hz, far bigger model than local |
| gpt-oss-20B on Groq | ~850 | 0.22 s (1k) | same |
| Claude Sonnet 5.5 (low effort) | ~100 | 0.8 s (1k) | slow tactical / quick frontier calls |
| GPT-6 Luna (non-reasoning) | ~110 | 0.8 s | same |
| Claude Opus 5.5 (low) | ~80 | 3.5 s | frontier: skills, memory, recovery |
| Claude Haiku 5.5, Gemini 3.5 Flash-Lite | 160-450 | 5-7 s (thinking included) | not for the loop as configured |

Details and sources: the research brief that produced this note covers 20 systems; the main ones
are below.

## Prior work that matters here

| System | Unit of action | Real time? | Who writes skills |
|---|---|---|---|
| [Voyager](https://arxiv.org/abs/2305.16291) | JavaScript skill program | no, server paused while GPT-4 answers | GPT-4 writes, runs, reads errors, a GPT-4 critic verifies, ≤4 retries, verified skills stored by docstring |
| [Cradle](https://arxiv.org/abs/2403.03186) | code skills over keyboard/mouse | no, game paused | GPT-4o from tutorials and exploration |
| [PORTAL](https://arxiv.org/abs/2503.13356) | behaviour tree in a DSL | yes, LLM offline | Qwen2.5-32B-Coder; kills/deaths and replay analysis drive revisions |
| [PUBG Ally](https://developer.nvidia.com/blog/how-krafton-built-pubg-ally-a-co-playable-character-powered-by-nvidia-ace/) | 2B model picks intent; behaviour tree acts | yes | hand-built tree; on-device because cloud was too slow |
| [DPT-Agent](https://arxiv.org/abs/2502.11882) | state-machine macro actions | yes, LLM async | LLM writes code that edits the state machine |
| [Lumine](https://arxiv.org/abs/2511.08892) | 200 ms chunks of keys + mouse | yes, 5 Hz | one 7B model; thinks every ~3 s |
| [Game-TARS](https://arxiv.org/abs/2510.23691) | raw primitives | partly | sparse thinking beat always/never thinking |
| [ROAR](https://arxiv.org/abs/2610.24282) | one action per call | yes | none; collapses under real time |

The Dreamer line (DreamerV3, Dreamer 4) is world-model RL, not code; at most a simulator to test
skills in.

## Proposed design

```mermaid
flowchart TB
    you(["you speak"]) --> voice["Voice (Gemma-12B)<br/>replies ~1.5 s"]
    you --> fast["Fast model (4B local or Cerebras/Groq)<br/>picks a skill: every event + 2-10 Hz, ~100-250 ms"]
    fast --> run["Skill runtime<br/>runs the skill every tick (30 Hz)"]
    run -- "keys, mouse" --> game(["Halo"])
    game -- state --> run & fast
    run -- "traces, failures" --> frontier["Frontier (Claude Opus/Sonnet)<br/>async: writes and repairs skills,<br/>memory, the fast model's prompt"]
    frontier -- "skills (tested), prompt, orders" --> run & fast
```

**Skill strata**
1. *Body API* (by hand, per game): move toward, aim at, fire, crouch, jump, reload, grenade; state:
   positions, enemies, cover, items, paths. The only game-specific part.
2. *Motor skills* (frontier, rarely changed): closed-loop controllers per tick: track, strafe,
   follow a path, peek. These give the smooth, 20 fps feel.
3. *Tactical skills* (frontier, refined from failures): flank, take cover from, clear a room,
   cover the player; each with its own timeouts, stuck detection and fallbacks.
4. *Orders and plans*: short sequences or state machines bound to what the player said; the fast
   model composes simple ones, the frontier writes complex ones.

**Recovery at three speeds**: in the skill itself (milliseconds, pre-written fallbacks); the fast
model switching skills (~100 ms); the frontier patching a skill or the prompt from the trace
(seconds to minutes; applies next time, after testing on recorded states).

**When the frontier writes or rewrites a skill**: no skill fits an order (the fast model says so);
a skill raises, stalls or keeps losing (deaths, no progress); the player corrects Kevin by voice;
the same sequence of calls repeats (compile it into a skill); a new level or enemy type.

**The fast model's prompt is the frontier's main lever**: only the few skills relevant now (small
models get worse as the menu grows), worked examples aimed at observed mistakes, standing orders.
Its decisions, relabelled by the frontier in hindsight, are cheap text-only fine-tuning data.

**Speed targets**: per-tick code 33 ms; tactical decision ≤250 ms from an event; an order starts
being carried out ≤1 s after the player stops talking (today ~2-6 s through Reflect); Voice ≤1.5 s
with a filler; frontier seconds to minutes, never in the hot path.

## First experiment (proposal)

The single-player m8 mode already has a body with tactical skills: Halo's own AI drives the
companion actor through ~17 actions (follow, go_to, shoot, cover, hold_fire...). Replace Kev with
a fast model that picks action and option on every event and at a few Hz, and let a frontier model
write composite skills in Python from those actions (flank = go_to a computed point, then shoot)
plus the fast model's prompt. Score it on the §10 failures: move in front, hold fire, get behind
the rock, flank right. Only then build the player-2 body API (state and per-tick input in Kevin's
native client) for the co-op version.
