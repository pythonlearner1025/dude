# Problems found so far

Everything we have observed while running m8's architecture (Python port `m8py`) in Halo CE, with
evidence, before choosing a design. Sources: two live sessions (`findings.md` §5 Qwen3.5-9B / b30,
§7 Gemma4-12B / a30; 148 player lines), fake-game benchmarks (§3), server benchmarks (§1-2, §6),
and the infrastructure work. (A replay benchmark was considered and dropped; later playtests in
`findings.md` §8-10 measure the same items live.)

Severity: **S1** breaks the experience, **S2** clearly hurts it, **S3** friction. Kind: **R** open
research/design question, **E** engineering with a known fix.

## A. Doing what the player says

| # | Problem | Evidence | Sev | Kind |
| --- | --- | --- | --- | --- |
| A1 | **Orders are forgotten within seconds.** The action picker sees only the newest 20 feed lines | "hold your fire" left Kev's window after 11 s, "always be ahead of me" 24 s, "go where I'm pointing" 27 s | S1 | R |
| A2 | **No representation for standing orders** ("always stay ahead of me and clear"). Nothing stores or enforces a rule | rule given at 6.6 min, never followed | S1 | R |
| A3 | **No conditional execution** ("hold fire until they're close"). Decisions happen only on events, never on a condition | m8 loop: one decision per event batch / quiet spell | S1 | R |
| A4 | **Missing skills.** The game offers ~10-15 atomic actions; many orders have no action to map to (lead ahead, move behind a landmark, board a specific seat, clear an area, fire-until) | offered set at 8.6 min: `stay, shoot_chief, switch_weapon, search_*, go_to, go_aim, jump, crouch, look, flashlight` | S1 | E (per game) |
| A5 | **No multi-step tasks and no outcome feedback.** Actions are fire-and-forget; nothing knows whether Kevin arrived, boarded, or got stuck, so nothing retries or reports | "get in" took ~6 commands; Warthog episode ~2 min | S1 | R/E |
| A6 | **Wrong mapping even when an action exists.** | "go where I'm pointing" → `follow` (twice) though `go_aim` was offered; "rush that portal" needed 5 repeats | S1 | R |
| A7 | **The decision model is not a game policy.** Kev is calibrated on documents/QA; on an 11-way game choice its top option had confidence ~0.10; Q4 and Q8 disagreed on the same prompt | §2, §6 | S2 | R |
| A8 | **Player commands don't pre-empt.** A command waits in the same queue as event batches and the mate's own turn | input queue wait p90 1.1-2.5 s, max 8.2-8.3 s | S2 | E |
| A9 | **Free-text targets don't match offered targets** ("portal", "the guy in the passenger seat") | §5 | S2 | R |

## B. Space

| # | Problem | Evidence | Sev | Kind |
| --- | --- | --- | --- | --- |
| B1 | **No terrain in the world description.** State names Kevin, the player and enemies (distance, bearing) — no rocks, cover, paths, vehicles' seats | state text, §7 | S1 | E (per game) |
| B2 | **Deictic references are unreliable.** "There / that rock / where I'm pointing" must be resolved by the action picker choosing `go_aim` or `go_to`, which it often doesn't | A6 | S1 | R |
| B3 | **The vision "spots" are a screen grid,** not places: 40 points in an 8×5 grid, some on water or the vehicle body; "behind X relative to the threat" is not expressible | frame at 20:17 (`go_to` → spot 14 "the Warthog's back seat") | S2 | E |
| B4 | **Vision is slow and mis-triggered.** 0.7-2 s per call on the critical path; in a10 the crewman's instructions to the Chief made Kevin `look` 9 times | §5, §7 | S2 | E |
| B5 | **Arriving ≠ doing.** Walking to a spot next to the Warthog isn't boarding; no path/stuck reporting | §5 | S2 | E |

## C. Saying vs doing

| # | Problem | Evidence | Sev | Kind |
| --- | --- | --- | --- | --- |
| C1 | **The voice narrates actions the body didn't take.** "I'm in, I'm in", "[hops into the passenger seat]", "On it! [charges forward]" while the chosen action was `follow`/`go_to`; described shooting himself when told to shoot a marine | §5, §7 | S1 | R |
| C2 | **The voice doesn't know what is possible.** It isn't told which actions exist or failed, so it improvises | §5 | S1 | R/E |
| C3 | **Bracket notes are conflated.** Every `[...]` becomes a TTS voice direction, including actions and sounds ("[rapid fire]" in ~40 lines; "[shoves a fresh mag into the assault rifle]") | 95/114 long notes with Qwen; ~40 `[rapid fire]` with Gemma | S2 | E |

## D. Talk quality and conversational policy

| # | Problem | Evidence | Sev | Kind |
| --- | --- | --- | --- | --- |
| D1 | **Monologues.** With Qwen-9B, median 96 words (13-18 s of speech); 53% of lines cut off by the player | §5 | S1 (model-dependent) | E |
| D2 | **Catchphrase loops and self-imitation.** "Fuck me sideways" ~15×, whole sentences repeated ×3-4; `[yelling…]` opens 56/70 and 55/88 lines (copied from the persona's own example) | §5, §7 | S2 | R/E |
| D3 | **Answers everything, including noise.** Fillers and fragments ("Okay, um", "Eighth.", "Refer.") each get a reply because the player is always answered | §7: 84 player lines in 8.6 min | S2 | E |
| D4 | **Ungrounded details.** Invented injuries, corpses; addressing the player as Cortana | §5, §7 | S2 | R |
| D5 | **No policy for initiative.** The mate spoke on 6-8% of game events; 50-60% of decisions fell in the fixed 5 s cooldown. We don't know what the right rate is | §5, §7 | S3 | R |
| D6 | **Stale context after a scene change** (answered in b30 about the a10 training room) | §5 | S3 | E |
| D7 | **Persona quality depends on the model more than the prompt.** Same prompt: Qwen-9B monologues, Gemma-12B short callouts and grounded banter | §7 | — (finding) | R |

## E. Hearing and turn-taking

| # | Problem | Evidence | Sev | Kind |
| --- | --- | --- | --- | --- |
| E1 | **STT mishears the mate's name and game terms**, and the mate replies to the mistake | "Kevin" → "Heaven", "Evan"; "aiming" → "eating"; "man" → "Matt" | S2 | E |
| E2 | **End of turn = 100 ms of silence,** so hesitations split one thought into several turns ("Apparently there's" / "Multiple Covenant drop ships approaching.") | §7 | S2 | E |
| E3 | **Mic state is not visible enough;** the first browser session ran without the mic and nobody noticed for minutes | session log | S3 | E |

## F. Memory and relationship

| # | Problem | Evidence | Sev | Kind |
| --- | --- | --- | --- | --- |
| F1 | **Memory is a rolling transcript plus one summary;** no structured facts (promises, preferences, running jokes, grudges). The best moment (the friendly-fire grudge) emerged by luck | §5 | S2 | R |
| F2 | **Silent overflow.** A 32k context split into 16k slots made every LLM call fail once the feed passed 16k tokens; the mate went mute with no visible error; folding uses a chars/4 estimate | §6 | S1 (when it hits) | E |
| F3 | **Memory scope is a product decision:** per level (wanted for testing, now implemented via `new_game`) vs a persistent friend across levels, games and sessions | user request | — | R |

## G. Latency, compute and serving (one RTX 3090 Ti)

| # | Problem | Evidence | Sev | Kind |
| --- | --- | --- | --- | --- |
| G1 | **Serial decision calls on the critical path:** 357-476 ms p50, 1.6-3.5 s with vision | §5, §7 | S2 | E |
| G2 | **Prompt layout defeats the prefix cache:** "Right now" is inserted before the newest lines, so live first token is 166 ms (Qwen) / 510 ms (Gemma) vs ~45 / ~170 ms with a cached prefix | §2, §6, §7 | S2 | E |
| G3 | **The brain is single-threaded:** while the mate is deciding or talking, the player's next line waits (queue wait max 8.3 s) | §5, §7 | S2 | E |
| G4 | **Quality vs speed trade in the LLM:** Gemma-12B is better company but ~3× slower to first token than Qwen-9B | §6, §7 | S2 | R |
| G5 | **No VRAM left:** m8's stack doesn't fit 24 GB as shipped; the fitted stacks use 21.6-22.2 GB, TTS alone 9 GB; no room for another model or a reasoning loop without giving something up | §1, §6 | S2 | E/R |

## H. Game integration and operations

| # | Problem | Evidence | Sev | Kind |
| --- | --- | --- | --- | --- |
| H1 | **The adapter is the per-game cost:** m8's Halo mod is a 5.8k-line patch to a decompilation; the action set, state text and referents are fixed by it | `games/halo` | S1 for "any game" | R/E |
| H2 | **Browser build lags on the Mac** (low CPU/GPU load); not reproducible on Linux/NVIDIA, where it matches upstream at 60 fps | `reports/halo-web-perf.md` | S2 | E (open) |
| H3 | **Cutscenes slow down testing;** now skipped where the scripts allow and fast-forwarded at ~8× elsewhere | `reports/halo-cinematic-fast-forward.md` | S3 (mitigated) | E |
| H4 | **Silent failures** (context overflow, mic off, disconnected game while the player kept talking) are invisible to the player | §6, sessions | S2 | E |
| H5 | **Game data must come from the player's own disc** for decompilation targets (Xbox image; PC/MCC data doesn't work) | setup | S3 | — |

## I. Evaluation

| # | Problem | Evidence | Sev | Kind |
| --- | --- | --- | --- | --- |
| I1 | **No objective measure of obedience or fun yet:** two sessions, ~150 player lines, anecdotes | — | S1 for progress | R |
| I2 | **The fake game has no spatial world,** so spatial commands can't be regression-tested | `m8py/fakegame.py` | S2 | E |
| I3 | **Free labels exist and are unused:** repeated commands, "you're not listening", corrections | §5, §7 | — (opportunity) | R |

## The problem, restated

The two playtests say the hard part is not talking. Latency is already conversational (0.9-1.4 s
to first audio), and with the right model the banter is short, grounded and fun. The hard part is
**obedience**: turning what the player says into behaviour that keeps holding, in space, over time,
and staying honest about it.

> Given a stream of player speech and the game's state and events, and a game-specific set of
> native skills, produce in real time on one consumer GPU (1) behaviour that complies with the
> player's immediate, standing, conditional, spatial and multi-step instructions, and acts
> sensibly when there are none, and (2) short, in-character speech that is true to that
> behaviour. Measured by compliance rate, time to comply, rule adherence over time, speech-action
> consistency, mouth-to-ear latency, and whether the player wants to play again.

Sub-problems, in the order they block the experience:

1. **Instruction persistence and execution** (A1-A5, A8): where an order lives, what enforces it,
   how tasks are sequenced, how outcomes come back.
2. **Grounding language in the game** (A6, A7, A9, B1-B5): mapping words, pointing and landmarks
   to skills and targets — a per-game policy, not a general-purpose decision model.
3. **Speech-action consistency** (C1-C3): the voice may only describe what the body is doing.
4. **Conversational policy** (D1-D6, E2): when to speak, how much, and when to stay silent.
5. **Perception of the player** (E1-E3): names, game vocabulary, end of turn.
6. **The compute budget** (G1-G5): every new loop competes with voice and TTS on one GPU.
7. **Memory as relationship** (F1, F3) and reliability (F2, H4).
8. **Cost per game** (H1) and **evaluation** (I1-I3), which decide whether any of this generalises.

## Constraints to design around in a fully neural Kevin

Decided: the current build does **not** hard-code these (no new game skills per order type, no
code-level condition watcher, no hard-coded arbitration between deciders). They stay open, as
requirements for a learned solution where the brain itself discerns and does this:

1. **The action list is a ceiling.** Kevin can only pick from the ~10-15 actions the game offers
   at that moment; "stay ahead of me", "behind that rock", "hold fire until close", "the passenger
   seat", "clear that area" have no action. A hand-written skill per order type is an
   ever-growing list; a neural policy must compose behaviour from low-level control.
2. **Conditions change without events.** "Hold fire until they're close" / "stay ahead of me"
   become due when an enemy crosses a distance or the player moves — not on any game event — so an
   event-driven decider never re-decides. A neural policy needs a continuous (tick-rate) view.
3. **Two deciders, no arbiter.** A fast decider (Kev) and a slow reasoner (Reflect) can undo each
   other's choices; who wins must be learned or structural, not a rule table.
4. **Orders scroll away.** A decider that sees only the newest ~20 feed lines loses an order in
   11-27 s (measured); persistence has to live in the model's state or memory.
5. **Movement outcomes need geometry.** Prose state ("close by", "ahead" relative to Kevin's aim)
   can't tell arrived / stuck / ahead-of-player; positions and headings are needed (being added as
   state contract v2).
6. **One GPU.** Voice, reasoning, vision, TTS and the game share one 24 GB card and one KV pool;
   every extra loop costs voice latency.
