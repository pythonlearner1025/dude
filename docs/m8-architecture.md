# m8 architecture (as read from chasmlol/m8 @ b009e12)

m8 is a ~2.5k-line Rust orchestrator: every model is an HTTP endpoint, m8 itself only runs
Silero VAD. The game is a thin "body" that reports the world in words and executes one action
at a time. This document is the reference the Python port (`m8py`) must match.

## Processes and ports

| Role | Server | Model (as shipped) | Port |
| --- | --- | --- | --- |
| Decide | llama.cpp `llama-server`, `POST /v1/systemone` | Kev-4B Q8_0 (Qwen3.5-4B-Base + decision head) | 8080 |
| Talk + see | llama.cpp, `POST /v1/chat/completions` (SSE stream, images as `image_url` data URIs, `response_format` json_schema) | Gemma4-12B QAT uncensored Q4_K_M + mmproj | 8081 |
| Speak | Breeze TTS 2 `POST /v1/audio/speech` (multipart; streams raw s16le mono; `GET /health` gives `sample_rate`; 409 while busy) | Breeze TTS 2 (3B) cloning `voices/soldier.wav` | 7860 |
| Hear | `POST /v1/audio/transcriptions` (multipart WAV → `{"text"}`) | Parakeet TDT 0.6B v2 int8 (sherpa-onnx, CPU) | 8083 |
| Game link | m8 listens, game connects (reconnects forever) | — | 47800 |
| Brain/history pages | m8 | — | 8090 |

## Threads (Rust) and data flow

```
mic (cpal) -> Listener: resample 16k -> Silero VAD (512-sample windows) -> segment + margins -> STT  --\
console stdin / site box ------------------------------------------------------------------------------>  inputs channel -> Brain (single thread, blocking)
game link reader: event/saved/loaded/direct ---------------------------------------------------------->        |
game link reader: kind-3 dialogue audio -> STT (own thread) -> waits out clip length -> Event --------/        |
                                                                                                                v
                                     Kev (systemone) calls, LLM stream -> sentences -> speech channel -> TTS thread -> kind-2 PCM frames -> game
```

`Speaking` (shared): `until` (when queued audio ends), `generation` (bumped on interrupt; every
LLM token / TTS chunk tagged with an older generation is dropped), `lines` (lines begun but not
fully voiced). `is_speaking = now < until + 500 ms`. `quiet_from = until` iff no line pending.

## The brain loop (`brain.rs`)

Inputs: `Heard(text)`, `Event{text, react}`, `Saved(id)`, `Loaded(id)`, `Summary{memory_gen, folded, text}`.

- Poll every 1 s. If nothing for 45 s and not speaking, not in combat, state non-null → synthetic
  event "It's been quiet for a while." (react) — and that is a "quiet" safe point for folding.
- Events are batched: after taking one Event, drain all queued Events (stop at the first
  non-Event, which is held for next iteration), then react once to the batch.
- `Heard`: send `{"type":"heard"}` to game, push `"{player}: {text}"` to feed, `respond(to_player=true)`.
- `Event`s: push each (with `{player}`/`{game}` filled) to feed; if any `react` → `respond(false)`.
- `respond`: cooldown = not to_player AND (a line is pending OR now < quiet_from + speech_cooldown (game setting, default 5 s)).
  `decide()`; if it says speak: interrupt current speech if speaking, then `say()`.
- After every input: `fold_over(quiet ? 16k : 20k tokens)` (tokens = chars/4).

### decide (Kev calls per turn: 1-5)
1. `act("do", state.actions)`: question `{"do":{"type":"choice","instructions":"Which of these does {name} do now?","criteria":{"nothing":"{name} carries on as he is", "<action>":"{name} <description>", ...}}}`.
2. If chosen action has `options` → second call `{"which":{"type":"choice","instructions":"<line>. Which one?","criteria":options}}`.
3. If action has `view` → `look()` (LLM vision call) instead of sending; else send `{"type":"action","action":..,"option":..}` immediately and append `result` text.
4. Feed gets `"{name} <description>[: <target label>][: <result or what he saw>]."`.
5. If the action has `then` → repeat steps 1-4 with `then` as the action list ("then" purpose).
6. If not to_player and not cooldown: `{"speak":{"type":"noul","instructions":"Should {name} speak now?"}}` → speak iff `noul >= 0.5`. Player lines are always answered.

Kev's prompt (`state` field, a single string): system prompt, level story + memory summary,
feed's last 20 lines split at the mate's last own line, with "situation" (combat/radio prompt
if flags set + "Right now: <state text>") inserted just before the lines since the mate last spoke.

### say (LLM)
Chat messages: system = persona; user = context (level story, "What {name} remembers: …");
feed lines before the newest-own-line boundary as alternating user/assistant turns (consecutive
same-role lines joined by `\n`; mate lines stripped of `"{name}: "`); then user = situation;
then the newest lines as user. Streams SSE; `Notes` splits `[direction]` notes out of the text
(each holds for following text), `SentenceSplitter` cuts at `.!?…` + whitespace or `\n`,
`clean()` strips brackets/markdown/emoji except the 4 Breeze sounds (`(laugh)`, `(sigh)`,
`(cough)`, `(clears throat)`, with 19 written variants). Each sentence → TTS job with the
current direction. Breaks if generation changes. Feed gets `"{name}: <raw full text>"`.

### look (vision; describe | choose)
Asks game for kind-4 view (2 s timeout). For `choose`, draws numbered discs on the spots
(3x5 bitmap digits, radius 15). PNG → base64 data URI. System: "You're the eyes of {name}…";
user: "Right now: …" + last 12 feed lines + question. `choose` uses `response_format`
json_schema `{place: string<=80, spot: int enum [0, ids…]}`; spot>0 → action sent with option
= spot id; feed text `"<place> (<metres> m off)"`. Views saved to `logs/views/<ms>.png`.

### memory
Feed > limit → fold oldest lines down to 12k tokens, on a background thread: LLM (temp 0.3)
rewrites previous summary + folded lines as a ≤250-word third-person past-tense memory.
Applied only if memory generation unchanged. Saves: `saves.json` keeps up to 50
`(save_id, {summary, feed})`; `loaded` restores the matching snapshot (else clears memory),
interrupts speech, sends `stop_audio`.

## Voice (`speak.rs`)
Per sentence: send `{"type":"say","text"}` to game, POST multipart (text, instruction?,
cfg_scale = 4 if instruction else 1, seed 42, ref_text, ref_audio WAV bytes) — retry 409 up
to 20×100 ms; stream s16le → kind-2 frames. First chunk of a new generation while older audio
still playing → `stop_audio` first. `End(gen)` → `audio_end` (if current gen) and `end_line`.

## Ears (`listen.rs`)
cpal default input → mono f32 → linear resample to 16 kHz → Silero VAD (threshold 0.5,
min silence 0.1 s, min speech 0, max speech 20 s) → segment with 200 ms pre / 100 ms post
margins from a 25 s ring buffer → STT. Barge-in: while mate speaking and VAD active → interrupt
+ `stop_audio`. Game `mic.muted` → feed nothing. Game dialogue (kind 3) is transcribed the same
way, then held until the clip would have finished playing, then becomes
`Event "<speaker>[ over the radio]: \"<text>\""`.

## Game protocol (TCP 127.0.0.1:47800)
Frame `[u8 kind][u32 BE len][payload]`. 1 = JSON both ways; 2 = mate PCM s16le to game;
3 = dialogue to m8 `[u16 BE jlen][json{speaker,radio,react,sample_rate}][s16le]`;
4 = view to m8 `[u16 BE jlen][json{width,height,spots[{id,x,y,metres}]}][RGB rows]`.
Game→m8 JSON: `state` (replaces latest), `event{text,react}`, `saved{id}`, `loaded{id}`,
`direct{text}` (→ "Game master: …"), `mic{muted}`, `settings{speech_cooldown}`.
m8→game: `hello{name,sample_rate}` on connect, `action{action,option?}`, `say`, `heard`,
`view`, `stop_audio`, `audio_end`.

## Latency anatomy of one spoken reply (player speech → first mate audio)
VAD end-of-speech (≥100 ms silence) → STT (Parakeet CPU) → Kev "do" (prefill of whole Kev
prompt; Kev server re-reads full prompt each call, `--cache-ram 0`) → [Kev "which"] → [vision
call] → [then: 1-2 more Kev calls] → LLM prefill (cached prefix thanks to stable prompt order)
→ first sentence complete → Breeze first audio (CUDA graphs) → game playback. Player lines skip
the "speak" call; game events add it. Every serial Kev call sits on the critical path.
