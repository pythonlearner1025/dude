# From m8 to any game: a companion runtime and a character factory

Brainstorm and proposal, written after reimplementing m8 in Python (`m8py`), running it on one
RTX 3090 Ti, and researching integration routes and model options
(`docs/findings.md`, `docs/research/games.md`, `docs/research/models.md`).

The thesis we started with holds up: the parts exist. What's missing is (1) a stable contract
between "a game" and "a character", (2) a cheap way to produce that contract for a new game,
(3) a loop that turns play into better characters, and (4) serving that leaves the game room to
run. This document proposes each.

---

## 1. What m8 gets right (keep these)

1. **The game narrates, the brain decides, the game executes.** The game sends the world as
   words (`state`), the *currently legal* actions with their targets, and events. The brain picks
   one action; the game runs it with native code (pathing, aiming, cover). No model ever drives
   motor control. This "affordance protocol" is the single most important idea: it makes the
   brain game-agnostic and keeps the model's job inside what small models do well.
2. **System 1 / System 2.** A closed-set decision model (Kev, via llama.cpp `/v1/systemone`)
   chooses actions and whether to speak; a generative LLM only writes lines. PUBG Ally (KRAFTON,
   2026: a ~2B on-device model over a behaviour tree, ~39k real sessions, +25.1 pt net
   willingness-to-recommend) is independent evidence that this split is the one that ships.
3. **One feed, stable prefix.** Everything said and done goes into one feed; prompts are ordered
   stable → volatile so the LLM's prefix cache hits (we measured 41-44 ms first token vs 220 ms
   cold).
4. **Voice in the world.** Speech plays through the game's own positional/radio audio, sentence
   by sentence, with `[voice direction]` notes and barge-in that cancels everything downstream via
   a generation counter. Presence comes from this, not from the model.
5. **Memory that follows saves.** Loading a checkpoint restores what the mate knew then. Elegant,
   and correct for single-player: memory is a branch of the save tree.
6. **Models are endpoints.** Every model is swappable behind an HTTP API. This is what made the
   port, the VRAM fit and the A/B plans cheap.

## 2. What the measurements say

See `docs/findings.md` for the tables. Headlines:

- **VRAM:** m8 as shipped (Kev-4B + Gemma-12B + Breeze 3B fast path) does not fit 24 GB.
  Swapping to Qwen3.5-9B fits at 21.6-21.8 GB, leaving ~1.2 GB for the game and streaming.
  Breeze TTS is the largest consumer (9 GB). Each model process also pays its own CUDA context.
- **Latency (isolated):** Kev 120-140 ms per decision call, and a turn makes 1-5 *serial* calls
  that each re-read the whole ~800-token prompt; LLM first token ~45 ms cached; vision on a 1080p
  frame ~2 s.
- **End-to-end (fake game, real models):** player speech end → first mate audio 0.8-0.9 s,
  game event → first audio ~1.1 s; Kev's chain and the LLM's first sentence are ~40% each. But a
  reply then runs 13-18 s of speech: the latency problem is solved before the *length* problem.
- **Decision quality signal:** Kev's calibration was fit on documents/QA, not game states; on an
  11-way game choice its top option had confidence 0.10 and `speak` hovered at 0.54. A
  general-purpose decision model is a format, not a policy: each game needs its own labels.
- **Persona:** the 9B uncensored model holds Kevin's voice well but writes longer lines than the
  persona asks for — length and repetition are the first things to train, not knowledge.

## 3. Where m8 stops generalising

| Limitation | Why it matters for "any game, rapidly" |
| --- | --- |
| The adapter is a 5.8k-line C patch inside a decompiled game | This is the real per-game cost; the brain is already generic |
| Decision chain is serial (do → which → then → which → speak), each a full prefill | Latency grows with action complexity; questions that share a state should be one call |
| Speaking is a per-event yes/no with a fixed cooldown | No model of pacing, intensity, the player's engagement, or what was already said |
| Memory = one rolling 250-word summary + 16k-token feed | No structured relationship memory (promises, preferences, running jokes, rivalries) → shallow, repetitive |
| Persona = prompt only | Long lines, drift; nothing improves with play |
| End of speech = 100 ms of silence | Mid-sentence pauses get cut; no semantic end-of-turn |
| Vision = full frame, synchronous | 2 s on the critical path of `look` / `go_to` |
| One process per model, 9 GB TTS | Leaves no room for the game on 24 GB |

## 4. Proposed architecture: a companion runtime

```
            ┌──────────────────────── per game (thin) ────────────────────────┐
 game ◄────►│ Adapter: state→prose, affordances (+preconditions), events,       │
            │ skills (native: path, aim, cover, loot), voice out, mic in, save id│
            └───────────────▲──────────────────────────────┬──────────────────┘
                            │ Companion Protocol v2 (m8's frames + capability manifest)
            ┌───────────────┴──────────────────────────────▼──────────────────┐
            │ Brain (game-agnostic)                                            │
            │  event bus → working feed → Director (pacing, initiative, intensity)│
            │  Policy: ONE decision call: {action+target, speak?, urgency}       │
            │  Dialogue LLM (persona LoRA) → sentence stream → TTS → voice frames│
            │  Memory: working feed │ episodic events │ relationship facts │     │
            │          save-branch snapshots │ cross-game identity              │
            │  Ears: VAD → end-of-turn model → streaming STT; barge-in, AEC      │
            │  Eyes: async, downscaled, event-triggered VLM captions             │
            │  Telemetry: spans, traces, audio, feedback → dataset               │
            └──────────────────────────────────────────────────────────────────┘
            ┌──────────────────────────────────────────────────────────────────┐
            │ Character pack: persona sheet, voice ref/design, style LoRA,      │
            │ policy head per game, lore/level packs, relationship state         │
            └──────────────────────────────────────────────────────────────────┘
```

### 4.1 Companion Protocol v2 (extend m8's, don't replace it)

Keep m8's framing (JSON / PCM / heard-audio / view frames) and add:

- **Capability manifest** in `hello` from the game: `body` (player | npc | possessed),
  `voice_out` (positional | radio | chat | local), `voice_in` (game | os), `view` (frames | none),
  `saves`, action schema version. The brain adapts (no `look` without frames, local TTS when the
  game can't play audio, etc.).
- **Actions as a lifecycle**, not fire-and-forget: each affordance carries `preconditions` already
  evaluated by the game, an `interruptible` flag and expected duration; the game reports
  `started / done / failed(reason) / stuck`. These become feed lines ("Kevin couldn't reach the
  ledge."), which is where a lot of grounded humour and honesty comes from.
- **Typed state alongside prose.** Keep the prose `state` for the models, add a small typed block
  (`hp`, `threats[]`, `ally_distance`, `in_combat`, `location_id`) so the Director and memory can
  compute without parsing text, and so policy training data has features.
- **Perception policy** in the adapter: server-side games (Rust, Minecraft plugins) know too much;
  the adapter must only report what the character could plausibly perceive.

### 4.2 The Director (new)

A small deterministic+learned component that owns *when* the character acts on its own:
time since last line, recent line similarity, intensity (from typed state), player speech rate
and recent barge-ins (a strong "too chatty" signal), and story beats (level start, death, loot,
milestones). It decides which events are worth a policy call at all, sets the speech cooldown
dynamically instead of a fixed 5 s, and injects "avoid repeating" lists. m8's cooldown is a
first version of this.

### 4.3 One policy call per turn

Ask `{action (joint with target when the target set is small), speak?, urgency}` in **one**
`/v1/systemone` request: the decision-model blog confirms questions in one request share a single
pass over the state. Second calls only when a game result really is new information
(m8's `then`). With a game-tuned small decision model (Julia 144M / Laya 421M: 3-5 ms per
question on a datacenter GPU, CPU-viable) the whole decision drops from ~0.3-0.7 s to tens of ms,
and frees ~5 GB of VRAM.

### 4.4 Memory that makes it a relationship

- **Working feed** (last 20-30 events, verbatim) — as m8.
- **Episodic log**: one record per meaningful beat (`when, where, who, what changed, feeling`),
  retrieved by entity/recency/similarity.
- **Relationship facts** with provenance: names, preferences, promises, running jokes, rivalries,
  grudges ("Kevin owes Chasm for the Hunter save"). These are what players notice and what
  generic summaries lose.
- **Save branches**: keep m8's idea — memory snapshots keyed by save id.
- **Cross-game identity**: the same character (voice, persona, relationship facts) can join you in
  Halo, then Minecraft, then Rust and remember. Game-specific episodic memory stays per game;
  the relationship carries over. This is the strongest product idea in this document: not
  "an NPC in a game" but **a friend who plays your games with you**.

### 4.5 Ears and mouth

- Silero VAD at ~200 ms + an end-of-turn model (Smart Turn v3, 8 MB, CPU) instead of 100 ms of
  silence; or Parakeet Realtime EOU (streaming STT + end-of-utterance in one 120M model).
- TTS with cloning + direction under ~4 GB (Qwen3-TTS 0.6B, Chatterbox-Turbo 350M) as the
  default arm; Breeze stays the quality/steerability reference (non-commercial weights).
- Echo-tagging of the mate's own audio so it's never re-transcribed; barge-in keeps the
  interrupted sentence so the character can acknowledge being cut off.

### 4.6 Eyes

Vision becomes a tool, not a channel: triggered by `look`/`go_to`, scene changes or ambiguity,
downscaled to ≤768 px, run asynchronously, and its caption enters the feed when ready. Never on
the critical path of combat decisions.


### 4.7 Following instructions: directives, a task executor, and spatial grounding

The two playtests (findings §5, §7) show the companion's biggest failure is not talk but
*obedience*: standing orders ("always stay ahead of me"), conditional orders ("hold fire until
they're close"), spatial orders ("go behind that rock", "go where I'm pointing") and multi-step
tasks ("go clear that area out") are forgotten in 10-30 s or never executable. m8's loop is
"one decision per event, one atomic action, picked from the last 20 lines" — there is nowhere for
an instruction to live, nothing that checks a condition every tick, nothing that knows where a
rock is, and nothing that sequences skills toward a goal. The fix is a layer between talk and
action:

```
player line ──► Router ──┬─ chat / question ───────────────► Dialogue LLM
 (STT)          (tiny)   ├─ filler ("okay", "um") ──────────► silence / 2-word ack
                         └─ command / order / cancel ─► Compiler (LLM, JSON schema,
                                                        grounded in skills + referents)
                                                             │
                     ┌───────────────────────────────────────▼───────────────────────┐
                     │ Directive store (blackboard, persists until revoked)           │
                     │  standing: lead(ahead=8 m) · fire(hold, until enemy<10 m)      │
                     │  task:     clear_area(landmark 12) → then regroup              │
                     └───────────────────────────────┬───────────────────────────────┘
                                                     │ evaluated every tick (10-30 Hz)
                     ┌───────────────────────────────▼───────────────────────────────┐
                     │ Executor: behaviour tree over the adapter's primitive skills   │
                     │  move_to(point) · take_cover(landmark, from) · engage(target) │
                     │  fire_mode(hold|free) · stance · board(vehicle) · follow/lead  │
                     │  + safety (self-preservation, no friendly fire)                │
                     └───────────────────────────────┬───────────────────────────────┘
                                                     │ lifecycle: started/done/failed(reason)
                                                     ▼
                            feed + Dialogue LLM ("In position." / "No path up there, Chief.")
```

1. **Router (every player utterance).** Classify into chat, question, filler, command, standing
   order, or cancel ("stop", "forget that"). A small classifier or one constrained LLM call.
   Fillers get silence — at ~10 player lines a minute this alone removes a lot of noise.
2. **Compiler.** One LLM call with a JSON schema turns a command into a *program* over the
   skills the adapter advertises (typed parameters, not free text): an immediate task, a
   standing rule with a condition and a scope, or a cancel. It is grounded in referents (below)
   and in the current directives, so "no, further left" edits the active task.
3. **Directive store.** Standing orders and the active task live outside the rolling feed, are
   shown in every prompt ("Standing orders: lead 8 m ahead; weapons hold until enemies are
   within 10 m"), on the brain page, and in memory snapshots, and persist until revoked or
   fulfilled. Nothing scrolls away.
4. **Executor.** A behaviour tree evaluated at game cadence composes primitive skills to satisfy
   the task and the standing rules at once (lead = keep a point N m ahead of the player along their
   heading, re-planned every tick; "hold fire until close" = fire mode gated on a distance
   condition). Conditions use exact typed state, not prose. Every task reports
   started/done/failed(reason) — the "honest failure" lines players liked come from here.
5. **Spatial grounding.** The adapter adds referents to the state: the aim point (world position
   and the object under the crosshair) and nearby landmarks (rocks, cover, vehicles, doors: id,
   position, size). The LLM only picks *which* referent ("the rock you're aiming at" → landmark
   12); geometry ("behind it relative to the threats", "ahead of the player") is code. Vision is the
   fallback when the referent isn't in the index. m8's screen-grid spots (`go_to`) become one
   referent source among several.
6. **Speech bound to execution.** Lines are generated after compilation with the program as a
   fact ("you are now: moving to landmark 12, weapons hold"), may only describe that, and task
   events produce short status lines. This closes the says ≠ does gap (findings §5, §7).
7. **Where Kev fits.** Unprompted, moment-to-moment choices (react to an event, whether to speak)
   remain a closed-set decision — now *within* the active directives, and trained per game.

**Free training signal.** Players label failures for us: the same command repeated within
~10 s, "you're not listening", "no, the other one", and corrections that edit the active task are
automatic negative labels for the router/compiler/executor; time-to-comply and rule adherence
(e.g. fraction of time actually ahead of the player while "lead" is active) are measurable from
telemetry. A command-following benchmark (scripted fake-game scenarios with a small 2-D world
model, plus replayed real logs) makes this a regression suite.

**Generality.** Each game adapter implements the same primitive-skill and referent interface
(Halo mod in C, Minecraft via Mineflayer, Rust via a server plugin); router, compiler, directive
store, executor and dialogue are shared. This is the piece that turns "an NPC that talks" into a
teammate that takes orders.


### 4.8 Alternative considered: three loops (reflex / voice / reflect)

```
mic (echo-cancelled) → VAD + end-of-turn → streaming STT ─┐
game: state (2 Hz), events, view frames ──────────────────┤
                               Router / Director (chat · command · deictic · look · event · plan · memory)
   (1) REFLEX: one batched decision call {action+target, speak?, is_command, urgency} → action in ~0.2-0.3 s
   (2) VOICE: LLM slot A, no reasoning, short lines, append-only prompt
   (3) REFLECT: LLM slot B, reasoning, every few s and after failures: plan, check promises vs outcomes,
       emit a validated action + feed note
   + async downscaled vision tool, memory service, Breeze TTS with barge-in
```

| Need (from the playtests) | Three loops | Directives + executor (§4.7) |
| --- | --- | --- |
| Command reaction latency | better: one batched call (~150 ms on Kev) vs m8's 357-476 ms chain | needs an LLM compile step (~0.5-1 s) unless fast-pathed |
| Voice latency | better: append-only prompt keeps the prefix cache (live first token 510 ms vs 157-181 ms cached on Gemma) | silent on it |
| Standing orders ("stay ahead") | weak: no durable store; REFLECT must keep re-issuing; no `lead` action exists | stored and enforced every tick |
| Conditional orders ("hold fire until close") | weak: noticed seconds late at REFLECT cadence | condition checked every tick |
| Deictic / spatial ("where I'm pointing", "that rock") | vision tool: 0.7-2 s, coarse 8×5 screen grid | aim point + landmarks from the game (instant, metric); vision as fallback |
| Multi-step tasks | REFLECT plans, but atomic actions have no done/failed; progress inferred from 2 Hz state | executor sequences skills, lifecycle events |
| Says ≠ does | detects after the fact (promise audit) | prevents (line generated from the chosen program) |
| Novel, unanticipated instructions | better: open-ended reasoning | limited to predefined skill/rule types |
| Per-game adapter work | lower: reuses the offered action list | higher: primitives, referents, lifecycle |
| 24 GB budget | risky: a reasoning cycle (300-800 tokens at ~70 tok/s) keeps slot B busy, slowing voice and TTS on the same GPU; two ~18k prompts overflow the shared 32k KV | compile only on commands; executor on CPU |
| Debugging / evaluation | behaviour emerges from prompts | typed directives are inspectable and testable |

Reading: the three loops are the better runtime skeleton (multi-rate, latency-aware, auditable),
but they don't by themselves supply the four things the failures point to: durable orders,
tick-rate condition checks, spatial referents, and action outcome feedback. A hybrid keeps the
three loops, has REFLECT write validated typed directives (not one-off actions), and lets a small
executor enforce them between REFLECT cycles. (Neither the replay benchmark nor the GPU
contention test was built; the chosen design and its playtests are in `findings.md` §8-10.)

## 5. The character factory (training infrastructure)

Goal: a new character for a new game in days, improving with every session.

1. **Play is the dataset.** `m8py` already logs every turn: exact rendered state, options,
   decision probabilities, lines, audio, timings, cut-offs. Add outcome events (action
   done/failed), and player signals: barge-ins, "shut up"/"nice" (keyword spotting), laughter
   detection on the mic, a hotkey thumbs up/down, and a post-session review page (the history page
   already shows every call — add "better/worse" buttons and pairwise picks).
2. **Policy per game (System 1).** Relabel logged states offline with a strong teacher model
   (several samples → option *distributions*, not argmax), mix in player-behaviour labels, train
   a small decision head (Julia/Laya fork, or `kev.train --init_from jaredpalmer/kev-4b`) with
   option-order permutation, `none`-answer minimal pairs and session-level splits; refit
   calibration on held-out game data; gate low-confidence actions to a safe default.
3. **Persona (System 2).** Persona sheet (authored) → a situation taxonomy mined from the game's
   logged states (combat, death, loot, idle, player teasing, player sad, etc.) → a strong model
   writes 2-10k short scripted lines across situations → human curation → style LoRA (SFT) on the
   9B → DPO on pairwise preferences along explicit axes (in character, funny, short, grounded,
   not repetitive).
4. **Voice.** Design a voice from a description (we did this for Kevin with Breeze's voice-design
   mode, no recorded actor needed) or clone a consented clip; validate with WER + speaker
   similarity + direction adherence.
5. **Simulated players for scale.** Replays of logged scenarios through the fake game plus an
   LLM "player" that talks (via TTS) give unlimited, repeatable sessions for regression and
   preference data — humans then judge pairs instead of playing every hour.
6. **Evaluation harness.** The fake-game benchmark (`m8py bench`) is the regression suite:
   mouth-to-ear p50/p95, event-to-ear, action validity, speak precision/recall vs labels,
   repeated-line rate, line length, persona consistency, memory precision, VRAM peak, game
   frame-time p99. The north-star metric is human: "want to play with them again?".

### Making adapters rapid

The adapter is the per-game bottleneck. Two levers:

- **A ladder of integration routes** (from `docs/research/games.md`): official mod/script API or
  open decompilation (OpenCE) → engine mod loaders (BepInEx/MelonLoader for Unity, UE4SS for
  Unreal, REFramework) → server plugins (Paper, Carbon/Oxide) → bot clients (Mineflayer) →
  pixels + input (vision-action models such as NitroGen/Lumine as a last resort for motor
  control). Offline/private only; never against anti-cheat.
- **Agent-written adapters.** The Companion Protocol + the fake-game conformance tests are a
  spec an AI coding agent can implement against a game's mod API or decompilation, the same way
  Codex built this port. An "adapter kit" = protocol SDK (C, C#, Java, JS, Lua), a conformance
  test suite that drives the real game headless where possible (OpenCE has a null renderer), and
  a skill-library template. This is where recent AI decompilation and modding proliferation pay off.

## 6. First targets

**Minecraft (Java):** Mineflayer bot as the body (a real player: inventory, combat, building),
`mineflayer-pathfinder`/`-pvp` as native skills, an optional Paper plugin for authoritative events
and save identity, Simple Voice Chat for positional voice out (`EntityAudioChannel`, 48 kHz PCM)
and player mic in. Private server or LAN; legit account. Lowest-effort, highest-fidelity target —
the right first port of the brain.

**Rust (Facepunch):** private server in the Modded category, Carbon or Oxide C# plugin owning a
scientist-derived companion NPC with deterministic follow/fight/loot/revive state machines;
`OnPlayerVoice` for the player's mic. Positional voice *out* is unverified (only an old
voice-packet proof of concept): ship with radio/chat + local TTS and spike voice injection
separately. No client modding (EAC).

Both reuse the same brain, persona, voice and memory — and the same character can follow you from
Halo into them.

## 7. Serving on one 24 GB GPU (v2 budget)

| Component | Placement | Budget |
| --- | --- | ---: |
| Dialogue + vision: Qwen3.5-9B Q4_K_M + mmproj (persona LoRA) | GPU, llama.cpp, 1-2 slots, ≤16k ctx | 7-8 GB |
| TTS: Qwen3-TTS 0.6B or Chatterbox-Turbo | GPU | 3-4 GB |
| Policy: game-tuned Julia/Laya | CPU (or GPU, <0.5 GB) | ~0 GB |
| STT + VAD + end-of-turn | CPU | 0 GB |
| Game + Sunshine/NVENC + transients | GPU | ≥6 GB headroom |
| **Total model VRAM** | | **~11-12 GB** (vs 21.6 GB today) |

Plus: consolidate processes where the runtime allows, one in-flight job per model with
backpressure, vision cancellable and lowest priority, and measure game frame-time p99 rather than
average FPS. Hosted fallback (dialogue/TTS only; policy stays local) for weaker GPUs.

## 8. Experiments, in order

1. **Turn latency without quality loss:** one batched policy call; Julia/Laya vs Kev on replayed
   states (accuracy vs our logged Kev choices + teacher labels); vision downscaling.
2. **TTS bake-off** on Kevin's designed voice: Breeze vs Qwen3-TTS 0.6B vs Chatterbox-Turbo
   (TTFA, VRAM, WER, similarity, direction adherence, and a blind "which sounds more like Kevin").
3. **End-of-turn:** Smart Turn v3 vs silence timer on recorded player speech (false cut-offs,
   end-of-turn delay).
4. **Persona LoRA + DPO** for brevity and non-repetition; A/B blind.
5. **Relationship memory** v1 (facts + episodic) and cross-session tests ("remember when…").
6. **Minecraft adapter** via an agent-written Mineflayer adapter against the conformance tests.
7. **Real Halo playtests** once game data is available: the human metric.

## 9. Risks and open questions

- **Licences:** Breeze TTS weights/outputs are non-commercial; uncensored derivatives have unclear
  provenance; Halo game data must be user-owned. Fine for exploration, not for a product.
- **Consent and safety:** player voice capture, cloned voices, uncensored models, minors.
- **Anti-cheat and ToS:** private/offline only; never inject into protected multiplayer clients.
- **Fun is not accuracy:** a companion that is too competent or too chatty is worse. The Director
  and preference data matter more than benchmark scores.
- **Per-game skills** (pathing, combat) remain real engineering; models can't paper over a body
  that gets stuck.
