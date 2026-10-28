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


## 5. Live playtest: Halo CE in the browser on a MacBook, models on b650s

Session `1793146655` (26 min; a10 training then b30 "The Silent Cartographer" beach and Warthog),
analysed with `tools/analyze_session.py`. Player on a MacBook (browser build, in-page mic with
echo cancellation), m8py + models on b650s over Tailscale (LAN, ~4 ms).

| Metric | Value |
| --- | --- |
| Turns | 172 (64 player lines, 108 game-event batches) |
| Mate lines | 70, **37 cut off** (player talked over him, or a newer turn replaced the line) |
| Words per mate line | median 96, max 213; almost every line is two paragraphs |
| Lines opening `[yelling …]` | **56 / 70** (copied from the persona's own example) |
| Game-event turns that spoke | 6 / 108 (6%); 76 of 146 Kev decisions fell in the speech cooldown |
| Actions | shoot 63, nothing 45, follow 11, look 9, go_aim 7, rush 4, go_to 3, search_vehicles 2 |
| Errors | none; VRAM 21.9-22.2 GB throughout |

| Latency (ms) | p50 | p90 | max | n |
| --- | ---: | ---: | ---: | ---: |
| Player speech end → first mate audio | **1 006** | 2 230 | 8 045 | 64 |
| Game event → first mate audio | 3 323 | 6 020 | 7 023 | 6 |
| Input queue wait | 0 | 2 461 | 8 294 | 172 |
| STT | 62 | 108 | 191 | 64 |
| Kev decision chain | 476 | 1 152 | 3 516 | 146 |
| LLM first token / first sentence | 166 / 363 | 286 / 430 | 689 / 785 | 70 |
| TTS first audio | 197 | 204 | 218 | 70 |
| Vision call | 1 420 | 1 935 | 3 025 | 11 |

What playing it actually felt like (from the transcript):

1. **Says ≠ does.** The dialogue model narrates actions the body never takes. Asked to get in the
   Warthog, Kevin said "I'm in, I'm in" and "[hops into the passenger seat]" for ~2 minutes
   while Kev chose `go_to`, `follow`, `search_vehicles`; he got in only at the end. Asked to kill
   the marine in the passenger seat (not an action the game offers), he described shooting
   *himself*. m8 puts the chosen action in the feed before the LLM speaks, but nothing stops the
   LLM from inventing others, and Kev never sees what the LLM promised. The persona's "what you
   say you'll do, you do" is not enforced by anything.
2. **Commands need repeating.** "Rush that portal" took 5 repetitions before Kev chose `rush`;
   "get in" ~6. Imperatives from the player are scored like any other context, with no
   "the player just told you to do X" priority, and with free-text targets ("portal") that match
   no offered option.
3. **Talking over a monologue.** With 15-30 s replies, the player interrupts constantly (37 / 70
   lines cut). Barge-in works technically; conversationally it turns every exchange into
   interrupting a speech.
4. **Catchphrase loops.** "Fuck me sideways" and "you damn block of concrete" each ~15 times;
   whole sentences repeated verbatim ("Finally! Don't tell me you got bored of running on
   foot…" ×4, "You heard me, Crush that portal before they swarm you!" ×3). The model imitates
   its own recent turns in the feed.
5. **Event confusion.** In the a10 training, the crewman's instructions to the Chief ("please look
   around the room") made Kev pick `look` for Kevin (9 vision calls at ~1.4 s each).
6. **STT on names.** "Kevin" → "Heaven", "man" → "Matt"; the mate then replied to the
   mis-transcription ("Heaven took that seat like a damn thief!"). Name/term biasing is needed.
7. **What worked:** voice and timing of the first audio (~1 s) felt live; barge-in; vision
   describing the scene accurately; and one genuinely good emergent moment — the player shot Kevin
   by accident, Kevin brought it up later, and held a grudge when the player apologised. That is
   the relationship texture worth designing for.

Cheap fixes these point to (not yet applied, to keep the m8 baseline): stop the LLM at the first
paragraph and cap tokens; ban the persona example strings and block n-grams from the last ~20
lines; tell the LLM exactly what the body did and can do ("you can't do X here; say so");
give the player's imperative a fast path (map it to an offered action or answer honestly that it
isn't possible); bias STT toward the mate's name and game terms; skip `look` unless the player
asked.

## 6. Back to m8's LLM: Gemma4-12B uncensored on 24 GB

BreezeBlue publishes a single TTS model (Breeze-TTS-2, 3B); there is no smaller official variant
(only community int8/int4/GGUF quantizations). Measured options for fitting Gemma4-12B:

| Stack (+ Xorg/Sunshine 0.29 GB) | VRAM | Result |
| --- | ---: | --- |
| Kev Q8 + Gemma 12B (`-np 2`) + Breeze eager (no fast flags) | 22.07 GB idle | **OOM on the first TTS request**: the streaming path still builds its decoder wrappers lazily (fp32 copy of the codebook head), +0.4-0.6 GB |
| **Kev Q4_K_M + Gemma 12B (`-np 2`) + Breeze fast (m8's flags)** | 22.10 GB idle, 22.16 GB peak during TTS | **fits**; this is m8's original stack except Kev's quantization |

With that stack (warm): Breeze first audio ~140 ms (RTF ~0.6); Kev Q4 155 ms per decision
(Q8: 141 ms — Q4 is not faster); Gemma first token 163-181 ms with prefix cache and 70 tok/s
(Qwen-9B: ~45 ms and 120 tok/s); Gemma vision 0.74-0.91 s on the same frame (Qwen: 2.0 s).
On the microbench prompt Gemma's lines were **one paragraph of ~30-40 words**, versus Qwen's
two paragraphs of ~100 — the brevity instructions are followed much better. Kev Q4 and Q8 chose
differently on the same 11-way prompt (`look` vs `shoot`, both at confidence ~0.1; the prompt
ended with the player asking "What do you see over there?", so Q4's pick is arguably better).
Launch: `infra/b650s/start-stack-gemma.sh` (and `start-stack-qwen.sh` for the fallback).

### A context-size trap (fixed)

Starting llama-server with an explicit `-np 2` switches the KV cache to per-slot
(`kv_unified = false`) and splits `-c 32768` into 16 384 tokens per slot. m8 assumes 32k per
request ("the servers take 32k a request"; the feed folds only above ~16-20k tokens by a
chars/4 estimate). After a long session the real request reached 18.1k tokens and **every** LLM
call failed with HTTP 400 (`exceeds the available context size (16384 tokens)`): the mate went
silent, with nothing visible to the player. Fix: `-np 2 -kvu` (both slots share one 32k pool;
`n_ctx_slot = 32768`). Two lessons for the runtime: count real tokens (the server's `/tokenize`)
instead of chars/4, and treat a context-size rejection as a signal to fold memory and retry, not
as a silent failure.

## 7. Second playtest: Gemma4-12B uncensored, a30 "Halo", fresh level start

Session `1793153795` (8.6 min): level grid → a10 → a30, `new_game` reset Kevin's memory on both
starts; a30's opening cinematic was auto-skipped. Stack: Kev-4B **Q4_K_M** + Gemma4-12B
(`-np 2 -kvu`) + Breeze (m8's fast flags). Same Mac browser setup as §5.

| | Qwen3.5-9B session (§5, b30) | **Gemma4-12B session (a30)** |
| --- | ---: | ---: |
| Player lines per minute | 2.5 | **9.8** (84 in 8.6 min) |
| Mate lines cut off | 37 / 70 (53%) | **12 / 88 (14%)** |
| Words per mate line, median (max) | 96 (213) | **11 (47)** |
| Speech per reply (turn start → last audio), p50 | 4.2 s (p90 20 s) | **2.3 s** (p90 4.4 s) |
| Stage actions sent to TTS as "directions" | 95 / 114 | **3 / 157** |
| Lines opening with `[yelling …]` | 56 / 70 | 55 / 88 |
| Player speech end → first audio, p50 / p90 / max | 1.0 / 2.2 / 8.0 s | **1.36 / 3.8 / 9.8 s** |
| LLM first token, p50 / p90 | 166 / 286 ms | **510 / 869 ms** |
| Kev decision chain, p50 | 476 ms (Q8) | 357 ms (Q4) |
| Input queue wait, p90 / max | 2.5 / 8.3 s | 1.1 / 8.2 s |
| Errors | none | none |

The earlier Gemma session `1793152598` (23 exchanges at the launcher, no game connected, so no
actions and no audible replies) had median 25 words and 0.91 s mouth-to-ear.

What it felt like (from the transcript):

1. **Squad chatter instead of speeches.** Short callouts ("On it! Watch your flank, Chief!",
   "Got one! That little squeaky shit's toast!") made rapid back-and-forth possible: the player
   talked ~4x more, and interrupted far less. Brevity, not latency, was the main fix: replacing
   the model fixed what the prompt alone could not.
2. **Orders landed more often:** "hide behind this rock" → `cover`, "hold your fire" →
   `hold_fire` (twice), "follow me" → `follow`, "get up" → `stand_up`, "time to get down" →
   `crouch`.
3. **Grounded banter, the good part:** "Isn't the sky beautiful?" → "It's fucking gorgeous, but
   it's gonna look real nice when that Banshee's guts are scattered across it!" (a Banshee
   appeared that moment); "holding on like a dog" → "That's a bit harsh, Chief. At least I'm a
   loyal one."; friendly fire → "Hey! You trying to kill me or—".
4. **Movement orders still fail: says ≠ does.** The last ~2 minutes were ~10 variants of "go
   where I'm pointing / go clear that area out / go in". Kevin answered "On it! [charges
   forward]" each time while Kev alternated `follow` and `go_aim` (twice `follow` for "go where I'm
   pointing"), until the player said "Not listening to me, man." Same failure as §5, now for
   movement: the line promises an action the policy didn't choose.
5. **New tics.** `[rapid fire]` inside ~40 lines (a sound/action note, useless as a TTS
   instruction), `[yelling]` openers 55 / 88, consecutive near-identical callouts ("Right side's
   mine!" twice).
6. **Answers to noise.** Fragments and fillers ("Eighth.", "Refer.", "Okay, um", "Yeah.") each got
   a reply because m8 always answers the player; at 10 player lines a minute that is a lot of
   unneeded talk.
7. **Hallucinated scene details** remain occasional ("[kicks the Elite's corpse]" before any
   Elite died; answering the player as if they were Cortana: "you glowing orb!").
8. **STT on names and terms:** "Evan" (Kevin), "where I'm eating" (aiming), "Targent", "Go clock".
9. **Cost of the bigger model:** first token ~3x slower than Qwen (510 vs 166 ms p50), so
   mouth-to-ear rose to 1.36 s p50 even though lines got much shorter.

Takeaways for the general architecture (§ `docs/general-architecture.md`):

- **Bind speech to the chosen action.** Generate the line *after* the action is chosen and pass it
  as a hard fact ("you are doing: go_aim"), forbid narrating other actions, or let one model emit
  {action, line} together. The persona's "what you say you'll do, you do" must be enforced by the
  runtime, not requested in the prompt.
- **A fast path for player imperatives.** Classify the utterance (command / question / banter /
  filler) first; map commands to an offered action with a small, game-tuned model; answer filler
  with silence or a two-word acknowledgement.
- **Sentence-level hygiene.** Strip or whitelist bracket notes (keep real voice directions, drop
  `[rapid fire]`-style actions), block n-grams repeated within the last ~20 lines.
- **Name/term biasing for STT** (mate's name, "aim", game vocabulary).
- **The model matters more than the prompt for brevity and banter** — a 12B that follows style
  instructions beat a faster 9B that didn't; keeping latency there needs a smaller/faster decoder
  or speculative decoding (Gemma's MTP draft head is published alongside the GGUF).

### Why orders don't stick (measured)

`tools/order_window.py` replays the feed and measures how long a player's order stays inside
Kev's view (m8 shows Kev only the newest 20 feed lines, `KEV_FEED_LINES`):

| Player order | Gone from Kev's window after |
| --- | ---: |
| "So hold your fire. Hold your fire." | 11 s |
| "Always be ahead of me." | 24 s |
| "Yeah, but let's hide behind this rock." | 24 s |
| "Behind that rock, go clear that area out." | 22 s |
| "Go where I'm pointing, go." | 27 s |

And even inside the window the order often had nothing to bind to: the actions the game offered
at that point were `stay, shoot_chief, switch_weapon, search_weapons, search_vehicles, go_to,
go_aim, jump, crouch, look, flashlight` — no "lead", no conditional fire, no "move behind X" — and
the state text names Kevin, the player and enemies but **no terrain** (no rocks, cover, paths). So:
standing orders are forgotten in ~10-30 s, conditional orders have no condition evaluator,
spatial references have no referents, and multi-step tasks ("go clear that area") have no
sequencer or completion events. These are architectural gaps, not model-quality gaps; the design
answer is §4.7 of `docs/general-architecture.md`.

## 8. Third playtest: first run of Kev / Validator / Voice / Reflect (a30)

Session `1793160871` (6 min, build `490aafe`; the first ~95 s were off-game talk picked up by the
mic, then a30 from a fresh start). 68 player lines, 33 Kevin replies, 44 Reflect calls.
Speech end → first audio p50 1.95 s.

| Problem seen | Measured | Cause | Status |
|---|---|---|---|
| Kevin froze in combat | 14 of 68 player lines got no decision; 43 s with no Kev call ("Don't shoot", "Stop shooting", "Kevin, hello?") | Joint action+target questions reached 644 tokens when a dropship unloaded; Kev's systemone needs the whole question in one micro-batch (512) and returned 400 | Fixed `bda2c0c`: Kev `-b/-ub 1024` (2048 needs a 2 GB compute buffer and does not fit); an 800-token question now passes; VRAM 22.3 / 23.0 GB |
| Kevin narrated himself in third person | 19 of 33 replies added a "Kevin is doing: leaning against a wall…" line; 11 such sentences were spoken | The Voice runtime rule told the model to "describe what he is actually doing according to the 'Kevin is doing' line"; each narrated reply then sat in the append-only history and was copied | Fixed `2bb183c`: rule now says speak only Kevin's words, never narrate; replaying this session's requests: old rule narrated 4/4, new rule 0/8 |
| Reflect made nonsense orders | Off-game talk became orders ("Place the phone sideways"); the internal trigger reason became an order ("Resume after voice.") | Reason line was in the prompt; no addressee signal | Reason removed from the prompt (kept in the trace). Off-game talk still becomes orders in replay (3/3): the transcript alone cannot tell who the player is talking to |
| Reflect memory filled with momentary state | `remember` grew to "Kevin is 6 m behind Chief", "Kevin is aiming at a boulder", "Kevin is badly hurt" and near-duplicate variants | Model re-emits the whole list with variations; code appended anything not matched exactly | `remember` is now a full replacement list and the prompt excludes positions/health/targets; replay: positions gone, health still slips in |
| Standing orders still did not stick | Final orders: `["be careful"]` | The conditional order ("wait for them to get off and then shoot") was given during the Kev outage; "stop firing, they're too far" was superseded seconds later by "shoot at these guys". Reflect itself was cut off 26 of 44 times by Voice; completed calls took 4-12 s | Not addressed |
| Kevin answered unevenly | Of 54 decided player lines, 31 got a reply; Kev's `speak` score for player lines sat at 0.46-0.56 | Speak? is asked for player lines too (by design), and the score is near the 0.5 cutoff for almost everything, including direct requests | Not addressed |
| Kevin reacted to insults nobody said | STT heard "Kevin" as "Jebby", "Debbie", "David", "Dabbit", "Devin", "Plate"; Kevin got angry at the "nicknames" and Reflect stored them as relationship facts | Parakeet has no bias toward the mate's name | Not addressed |
| Kevin was cut off constantly | Many replies cut mid-sentence | VAD splits one utterance into fragments ("Uh", "Like", "Yeah.") and each fragment barges in and starts a new turn | Not addressed (known since §5) |
| Voice claimed actions it was not doing | "firing a rapid burst at the grunts" while the chosen action was `nothing`; "Shoot at that guy" → `go_aim` | Voice still free-writes action claims; Kev picked the wrong action | Not addressed |

The direct reflex worked when Kev was up: "Kevin, stop firing… you're not hitting any of them"
→ `hold_fire` with is_command 0.64.
