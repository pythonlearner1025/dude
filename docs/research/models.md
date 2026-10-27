# Real-time voice AI game companions: model, training, and serving research

**Research date:** 27 October 2026. **Scope:** one consumer RTX 3090 Ti (24 GB), with emphasis on 2025–2026 releases. Numbers labelled **m8 measurement** come from the task brief rather than a public benchmark. Numbers labelled **vendor claim** have not been independently reproduced here. “VRAM not reported” means that the primary project does not publish a comparable figure; community measurements are included only when clearly marked.

The short recommendation is: move the decision path to a sub-billion-parameter model (or a game-tuned Kev adapter only if evaluation proves the smaller model inadequate); keep Qwen3.5-9B Q4_K_M as the single vision/dialogue model; replace Breeze's CUDA-graph fast path with a 0.6B–0.5B TTS; run VAD, end-of-turn detection, and preferably STT on CPU; and reserve several GB plus scheduling headroom for the game. Train the action/speak policy from exact game traces with option-order augmentation, soft teacher labels, held-out calibration, and mission/session-level evaluation. Train persona separately with short scripted SFT followed by preference tuning; do not mix action policy into the dialogue model.

## 1. Decision models, `/v1/systemone`, and a game-specific training plan

### What the endpoint is

llama.cpp merged [PR #29818](https://github.com/ggml-org/llama.cpp/pull/29818) on 2 October 2026. Its `/v1/systemone` route follows TypeSafe Jev's “System One” wire format: one `state` (text, JSON, chat messages, and for supported models images) plus any number of named questions. A question is `choice` (distribution over caller-supplied options), `score` (distribution and expected index over 2–10 ordered levels), or `noul` (probability of yes). There is no free-form decoding and `usage.output_tokens` is zero. The [ggml/Hugging Face announcement](https://huggingface.co/blog/ggml-org/decision-models-in-llamacpp) describes it as scoring allowed options in a forward pass, not generating an answer.

This is a constrained *contract*, not a guarantee of correctness. Option descriptions, option order, confidence calibration, and a deliberate `none`/`wait` action are part of the model input and must be evaluated. A probability of 0.9 is meaningful only after checking reliability on the new game's held-out traces.

The initially supported families are structurally different:

- **Kev-4B** is a frozen Qwen3.5-4B-Base backbone plus a 33.8M-parameter rank-16 LoRA and pointer head. Two projections compare each option-closing token with the question-final token; softmax produces the distribution. Kev's card publishes its [architecture, calibration, and context limits](https://huggingface.co/jaredpalmer/kev-4b#model-details). Its training mix is unusually reproducible: 12,576 base records, 1,425 date/missing-evidence records, 5,219 real-document records, 6,000 generated “skills” records, 5,320 developer-tool records, and replay from the base stage. Training uses option cross-entropy, shuffling, distractors, and missing-answer minimal pairs; the full [data and recipe are in the model card](https://huggingface.co/jaredpalmer/kev-4b#training-data). It is Apache-2.0.
- **lev (4B)** uses Qwen3.5-4B plus LoRA, label-token readout for moderate option sets and a candidate-path head for larger sets, followed by per-mode/per-option-count temperatures. Its published run used 200,000 examples from 29 sources, LoRA r=32/alpha=64 for three epochs on one H100 (7.8 hours); some source datasets have extra/non-commercial terms despite the adapter's Apache-2.0 label. See the [lev training and licence notes](https://huggingface.co/interfaze-ai/lev#training).
- **Laya (421M)** fully fine-tunes ModernBERT-large and adds two transformer layers, an option-marker scorer, and an act/escalate head. Each option is scored at its own `[MASK]`. Its project describes RLCD: Gaussian logit exploration, proper-scoring-rule reward (log+spherical and ranked probability score for ordinal questions), REINFORCE with a group-mean baseline, and TD over multi-turn prefixes. The [Laya card](https://huggingface.co/Gtrkrsk/laya) describes the architecture and method. A later independent CE-only reproduction reports that ordinary cross-entropy can match or beat the RL term on its benchmark; that is useful evidence, not proof for game traces ([model card and results](https://huggingface.co/minhleduc/laya-typed-decisions-ce-1024)). Apache-2.0.
- **Julia-1 (144.3M)** starts from multilingual mmBERT-small, adds a decision head, and trains on private decision-format examples. Its weights and inference code are public, but its training pipeline/data are not; do not claim reproducibility. The [Julia model card](https://huggingface.co/SupersonicLabs/Julia-1) reports Apache-2.0, 2–20 options per native call, and up to 8,192 combined tokens.
- **OpenJev (27B)** is a Qwen-family vision-language model trained so the first output-position logits over option letters carry the answer, with explicit option-order consistency training and post-hoc calibration. It reports 84.0% over 10,000 held-out text questions and strong browser/screenshot gains, but its weights are **CC BY-NC 4.0**, not commercially usable without another licence. Its primary runtime is FP8 on an H100; GGUF Q4 is text-only. See its [method, formats, and licence](https://huggingface.co/openjev/openjev#how-it-works-in-one-paragraph).

### KV reuse and m8's repeated prompt cost

Within **one** System One request, batching questions is already the reuse mechanism. The announcement explicitly says questions are independent and Kev, lev, and OpenJev process the state once; Kev's own card says each question continues from the shared cached state ([announcement](https://huggingface.co/blog/ggml-org/decision-models-in-llamacpp#tips), [Kev details](https://huggingface.co/jaredpalmer/kev-4b#model-details)). Therefore put `action`, `target`, and `speak?` in one request whenever they depend on the same state.

That does **not** make several HTTP calls share a live KV sequence. m8's measured 2–5 serial calls, each re-reading roughly 800 tokens in 120–140 ms, are separate requests. llama.cpp may obtain a prefix-cache hit when the token prefix is identical and resident, but a changed feed, appended search result, or independently rendered question can invalidate much of it. Router unload/sleep also destroys the useful cache. Moreover, questions in one request cannot condition on one another: lev explicitly documents this independence. A search result that only exists after the first action necessarily requires a second decision call.

Practical reduction:

1. In the first call ask a joint action choice (including `none`) and `speak?`; include target as part of the action option if the target list is small. This removes a serial call and avoids an inconsistent action/target pair.
2. For large target sets, first choose action, then choose target only if needed. Do not issue target/speech calls speculatively.
3. Canonicalize the stable prefix byte-for-byte and append volatile state last; verify cache hits from server timing/metrics rather than assuming them.
4. Replace Kev with Laya/Julia or a custom 100M–800M encoder if held-out game accuracy remains acceptable. At m8's measured latency, eliminating four 130 ms calls saves far more than small decode optimizations.

### Concrete custom training plan for a new game

**Schema and logging.** Log the exact rendered `state`, ordered candidate IDs/descriptions, chosen action and target, the `speak` decision, timestamps, mission/save ID, player/session ID, downstream result, interruptions/corrections, deaths/reloads, and player feedback. Preserve impossible and “do nothing” situations. Redact player speech before publishing. Turn each state into:

- a `choice` question over legal joint `(action,target)` candidates plus `none`;
- a separate `noul` for “should the companion speak now?”; and
- optionally an ordinal urgency/interruptibility `score`.

**Labels.** Player actions are not automatically optimal labels. Use three streams:

- *Behavioural*: accepted action, cancellation, immediate correction, combat outcome, friendly fire, distance/formation error.
- *Teacher distillation*: give a stronger VLM/LLM the exact state and candidates, sample several seeds or several teachers, and retain the vote distribution rather than only the argmax. Add rationales only as offline audit material; the student target is the option distribution.
- *Preference*: show players two short rollouts or responses; convert pairwise wins into weights/rewards. For `speak`, collect “welcome / annoying / should have spoken” at event boundaries. Counterfactual clips are more useful than a generic thumbs-up.

**Splits.** Deduplicate near-identical ticks, cap repeated idle/combat states, and split by entire mission **and** player/session. Keep a locked stress set for rare events, ambiguous states, option permutations, missing evidence, and adversarial player lines. A random row split will leak adjacent ticks and substantially overstate quality.

**Training recipe.** The most direct route is the published Kev continuation interface (`kev.train --init_from jaredpalmer/kev-4b`) documented on [Kev's card](https://huggingface.co/jaredpalmer/kev-4b#intended-uses). With Hugging Face Transformers + PEFT, start from the exact Qwen3.5-4B-Base revision, load Kev's LoRA and head, and train the head plus LoRA—not the full 4B base. Start with rank 16, alpha 32, bf16, gradient checkpointing, effective batch 8–32, and 1–3 epochs; tune on validation NLL rather than copying those values blindly. Plain CE accepts hard labels; soft-label cross-entropy or KL accepts teacher/player vote distributions. For ordinal scores add ranked-probability loss; for binary speak include class weighting or focal sampling if “silent” dominates.

Hugging Face [TRL](https://huggingface.co/docs/trl/quickstart) supplies SFT/DPO/GRPO trainers, but Kev's nonstandard pointer head needs a custom `Trainer.compute_loss` or the Kev trainer. **Unsloth is useful for an ordinary Qwen LoRA/persona model, but it is not a drop-in trainer for Kev/Laya's custom head** unless its training loop is adapted. For a smaller policy, fork Laya's released code or train a ModernBERT/mmBERT option-marker head with ordinary CE first; RLCD is not the necessary starting point.

Augment every epoch with option permutations, paraphrased descriptions, distractors, `none` with the correct answer removed, and minimal state changes that should flip the action. Replay 20–40% generic decision data to avoid catastrophic format forgetting. Fit temperature(s) only on a held-out calibration split, freeze them, then report top-1/action accuracy, target accuracy, Brier/NLL, ECE, confident-error rate, abstention coverage at a chosen error budget, action churn per second, friendly-fire/death rate, and speech precision/recall. Export/merge only after evaluation, convert with the current ggml converter, and verify probability parity against the PyTorch model before deploying GGUF.

### Recommendations for a general companion stack

- Default to **Laya or Julia on CPU** for v2 exploration; promote to a game-tuned Kev only if the smaller model misses meaningful tactical distinctions.
- Make the policy output one joint legal action plus `none`, and batch `speak?` in the same System One request.
- Train from exact traces with soft teacher/player labels, option-order augmentation, session-level splits, and post-hoc calibration.
- Use a confidence/entropy gate and safe fallback (`none`, maintain formation, or a deterministic rule) instead of blindly executing low-confidence actions.
- Keep policy and persona training separate: the former is closed-set and calibrated; the latter is generative and stylistic.

## 2. Character/LLM: an entertaining, consistent persona under 9B

### Recommended model

For the stated 24 GB target, **Qwen3.5-9B Q4_K_M plus its vision projector** is the most practical single dialogue/vision model found. The official Qwen card describes a 9B causal VLM, 262,144 native context, 201 languages, and Apache-2.0 weights ([official model card](https://huggingface.co/Qwen/Qwen3.5-9B)). HauhauCS's aggressive uncensoring release publishes a 5.3 GB Q4_K_M GGUF and 880 MB BF16 vision projector and claims 0/465 refusals ([model card](https://huggingface.co/HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive)). The refusal result and “zero capability loss” are **author claims, not independently verified here**; evaluate safety, visual grounding, dialogue quality, and commercial provenance yourself.

The task's Gemma4-12B HauhauCS Q4 stack is larger and uses the Gemma licence. It is plausible where 32 GB is available, but the supplied 3090 Ti test already shows that replacing it with 9B is what makes the whole stack fit (21.6 GB measured). Under the requested ≤9B ceiling, Qwen3.5-9B is the clear first candidate; the official aligned model is the safer licensing/provenance baseline, and the uncensored derivative is an optional A/B arm.

The measured 2 seconds for a 1080p frame is too slow for the control loop. Downscale/crop to 512–768 px, send a HUD-free region of interest, and run visual captioning asynchronously only on events or scene change. The decision model should continue from structured game state while the newest caption becomes advisory memory. Never block basic combat actions on a fresh full-frame caption.

### Persona training pipeline

**1. Prompt and data before tuning.** A strong, compact persona prompt should contain immutable identity, relationship, goals, speech rhythm, humour mechanisms, taboos, and 8–20 short examples. Keep lore facts outside the style block. Write 2,000–10,000 short, high-quality scripted exchanges across combat, failure, silence, repetition, mission transitions, teasing, apology, player interruption, and “nothing useful to say.” Include delivery tags and non-verbal events only if the selected TTS actually supports them. Keep most targets one sentence; length is learned.

**2. Persona LoRA/SFT.** Fine-tune the 9B model with a low-rank adapter (r=8–32 is a sensible sweep) on assistant tokens only. Mix 10–30% general instruction/dialogue replay to preserve vision and instruction following. Hold out whole scenarios and authors. Train a text-only style LoRA first; then test whether enabling it during image requests harms vision. Qwen's vision-language base can be tuned through Transformers/PEFT; Unsloth can reduce memory for conventional Qwen LoRA, while TRL's `SFTTrainer` is the straightforward reference implementation ([TRL quickstart](https://huggingface.co/docs/trl/quickstart)).

**3. Preference tuning.** Generate 3–6 candidates per situation, then collect pairwise choices on five explicit axes: in-character, funny/interesting, concise, contextually correct, and not repetitive. DPO is simpler and more stable than online RL for this scale. Do not collapse all axes into “funny”: a joke that breaks mission context should lose. Include negative pairs for monologues, catchphrase repetition, fake memories, narrating visible UI, and speaking over urgent audio. Retain a small KL/reference constraint or replay set so “short and funny” does not erase task competence.

**4. Evaluation.** Use blind pairwise human tests, character-identity classification, contradiction checks against the persona sheet, median spoken duration, interruption rate, distinct n-grams/catchphrases over a 30–60 minute session, and memory precision. LLM-as-judge can filter data but should not be the only evaluator because the same teacher can imprint its humour preferences.

### Memory and anti-repetition

Use a hybrid rather than putting a 16k transcript into every prompt:

- **Working feed:** last 10–30 dialogue/action events verbatim.
- **Episodic timeline:** one compact event record per meaningful beat: `(game time, level/location, participants, what changed, emotional tag, source IDs)`. Retrieve by entity + recency + embedding, with diversity/MMR.
- **Durable facts/relationship state:** structured facts with provenance, confidence, valid-from/valid-to, and contradiction handling (“player prefers stealth”, “Kevin owes player one”).
- **Chapter/save summary:** deterministic summary at quiet moments, versioned with the save. Loading a save restores the matching memory branch rather than facts learned in the abandoned future.
- **Knowledge graph only where it pays:** recurring characters, promises, quests, possessions, causal links, and temporal changes. Recent work increasingly combines episodic, semantic, and graph views rather than choosing one—see the 2025 [AriGraph](https://www.ijcai.org/proceedings/2025/0002) result for text-game agents and the 2026 [MAGMA multi-graph architecture](https://aclanthology.org/2026.acl-long.1709/). A graph is unnecessary for every quip.

For anti-repetition, store the companion's last 50–200 utterances separately. Before generation, inject only a compact “avoid these recent openings/catchphrases” list. After generation, compare the candidate with recent lines using normalized n-gram overlap plus an embedding similarity threshold; regenerate once with a targeted negative instruction, then fall back to silence or a neutral short acknowledgement. Apply repetition penalty only to prior **assistant** text; global token penalties can damage names and grammar. Use moderate temperature/top-p and a 2–4-gram blocker for exact loops. Training with explicit repetitive negatives helps; DITTO is one published repetition-penalization method ([NeurIPS paper](https://proceedings.neurips.cc/paper_files/paper/2022/file/148c0aeea1c5da82f4fa86a09d4190da-Paper-Conference.pdf)).

### Recommendations for a general companion stack

- Use one Qwen3.5-9B Q4_K_M VLM for both lines and event-driven vision; benchmark official vs HauhauCS rather than assuming “uncensored” means better character writing.
- Create a compact persona SFT LoRA, then DPO on in-character/concise/non-repetitive pairwise preferences.
- Keep working history, episodic events, durable facts, and save-branch summaries separate; retrieve a small, provenance-bearing bundle per turn.
- Gate every utterance through recent-line similarity and permit silence. Anti-repetition is partly a product policy, not just a sampler setting.
- Downscale/crop vision and run it asynchronously; structured game telemetry remains the real-time control source.

## 3. Speech: TTS, STT, turn taking, and full duplex

### TTS findings

There is no single winner across cloning, direction control, commercial licence, quality, and low VRAM. The most relevant choices are:

- **Qwen3-TTS 12 Hz 0.6B Base:** 3-second voice cloning, 10 languages, streaming architecture, Apache-2.0. The paper reports **97 ms first packet** (vendor benchmark, hardware/path dependent) and the official [0.6B model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base) confirms cloning. A published BF16 deployment measures 2,675 MB VRAM and RTF 0.13, but that is a third-party optimized package, not the upstream runtime ([measurement](https://huggingface.co/HamzaBrh/qwen3-tts-0.6b-bf16)). This is the best first v2 experiment for memory.
- **Chatterbox family:** the October 2026 upstream project now recommends **Turbo (350M)** for low-latency English voice agents: zero-shot cloning from a reference clip, native `[laugh]`/`[cough]`-style tags, and a distilled one-step speech-token-to-mel decoder. **Nano (110M)** shares that architecture, clones a reference, and is claimed to run 3× realtime on eight CPU cores. The 500M original and Multilingual V3 retain zero-shot cloning; the original exposes `exaggeration`/CFG controls and V3 covers 23+ languages. The repository and model family are MIT. No comparable self-hosted 3090 Ti TTFA/VRAM figure is published, so community 4–5 GB figures for the old model remain **unverified**. See the [official model matrix and licence](https://github.com/resemble-ai/chatterbox).
- **Breeze TTS 2:** the best direct fit for voice clone + free-form voice direction + vocal events. Upstream now reports 7.7 GiB eager, 14.4 GiB with `--fast-all`, <40 ms warmed TTFA and RTF 0.32 on H100; 12 GB/24 GB are the recommended eager/fast cards ([official runtime README](https://github.com/breezeblue-ai/breeze-tts)). Its weights and self-hosted outputs are research/non-commercial, and commercial use needs a separate agreement ([licence](https://huggingface.co/BreezeBlue/Breeze-TTS-2/blob/main/LICENSE)). The task's ~9 GB measurement is plausible for a different graph/runtime configuration but is not the current upstream fast-path figure.
- **Orpheus 3B:** preset voices, expressive tags such as laughter/sigh, zero-shot cloning in the broader project, and about 200 ms streaming latency (vendor claim; ~100 ms with input streaming). Only the 3B path was production-ready in its original package. Verify the exact checkpoint licence before shipping; the repository code is Apache-2.0, but model/data terms can differ ([project](https://github.com/canopyai/Orpheus-TTS)). Its memory footprint is unattractive beside a 9B VLM.
- **Dia 1.6B:** excellent two-speaker/dialogue and non-verbal events; 5–10 second audio prompting/voice cloning; Apache-2.0. The project reports ~4.4 GB VRAM in bf16/fp16 on RTX 4090 and 1.3–2.2× real-time, but recommends 5–20 second outputs and is not optimized for tiny turn fragments ([official repository](https://github.com/nari-labs/dia)).
- **F5-TTS:** strong zero-shot cloning and ~336M parameters, but public weights are CC BY-NC 4.0 and its native flow/diffusion path is not inherently streaming. The official TensorRT deployment reports 253 ms average on L20 at concurrency two and RTF 0.0394 ([official repository](https://github.com/SWivid/F5-TTS)); do not transfer that number to PyTorch/3090 Ti.
- **Fish Speech:** S2-Pro offers cloning, inline direction, streaming, and 50+ languages, but requires about 24 GB by itself. The October 2026 Fish Audio Community Licence permits some sub-$500k product use but prohibits a self-serve hosted TTS service without a separate licence; game-character generated speech is explicitly not treated as a hosted service. Drama 3 requires at least 48 GB. See the [official install requirements](https://github.com/fishaudio/fish-speech/blob/main/docs/en/install.md) and [licence](https://github.com/fishaudio/fish-speech/blob/main/LICENSE).
- **Higgs Audio v3 4B:** 100+ languages, clone and inline direction, but research/non-commercial weights; a community runtime reports ~11 GB bf16, 6–7 GB int8, 3.5 GB 4-bit, so these VRAM numbers are **not upstream-verified**. It is too large for the preferred one-card stack unless heavily quantized ([official project/licence](https://github.com/boson-ai/higgs-audio)).
- **NeuTTS Air/Nano:** on-device GGUF, instant cloning, streaming on the GGUF path, but no free-form emotion control for Air/Nano; NeuTTS-2E has six fixed emotions and four speakers. Licences vary by checkpoint (Apache-2.0 vs NeuTTS Open License 1.0), so inspect the selected model rather than the repository label ([official matrix](https://github.com/neuphonic/neutts)).
- **VibeVoice:** the original TTS code was removed after misuse. The 0.5B Realtime model returned in December 2025 with streaming and fixed/experimental speakers, while larger cloning variants are heavier. Availability and redistribution terms must be checked per checkpoint; it is not the clean default for a product ([official repository/status](https://github.com/microsoft/VibeVoice)).
- **Sesame CSM-1B:** conversational audio generation conditioned on audio/text, Apache-2.0 code/model declaration, but the released 1B checkpoint is an audio generator rather than the full Sesame conversational product and publishes no authoritative low-latency 3090 Ti number ([official repository](https://github.com/SesameAILabs/csm)).
- **Kokoro-82M:** Apache-2.0, extremely small and fast, but preset/style voices rather than true arbitrary zero-shot cloning. It is a good emergency/fallback voice, not a drop-in replacement for Kevin's cloned actor ([model card](https://huggingface.co/hexgrad/Kokoro-82M)).
- **Kyutai Pocket TTS:** lightweight CPU-oriented, audio streaming, cloning, CC BY 4.0, with English/French/German/Portuguese/Italian/Spanish in the 2026 configuration. It is worth a CPU-offload experiment when GPU frame time matters ([official model card](https://huggingface.co/kyutai/pocket-tts)).

Quantizing autoregressive TTS backbones can save memory, but vocoders/codecs, depth decoders, and reference encoders often remain FP16/BF16 and can dominate quality or workspace. Breeze's community C++ port reports Q4 at roughly 3 GB versus 7 GB F16, but also reports much worse CUDA performance because its small graphs are rebuilt; that is promising memory evidence, not a production recommendation ([port measurements](https://github.com/HoppouAI/Breeze-TTS-2.cpp/blob/main/docs/build.md)). Require an A/B test of speaker similarity, emotion adherence, WER, TTFA, RTF, and glitches before accepting a TTS quant.

### STT and turn taking

Parakeet TDT 0.6B v2 int8 is a reasonable batch/utterance recognizer, but Silero VAD alone cannot know whether a pause completes a thought. Two current local alternatives are especially relevant:

- **NVIDIA Parakeet Realtime EOU 120M v1** combines streaming RNNT transcription and an emitted `<EOU>` token, with 80–160 ms algorithmic latency, English only, no punctuation/capitalization, and NVIDIA Open Model License; NVIDIA says it is ready for commercial/non-commercial use ([model card](https://huggingface.co/nvidia/parakeet_realtime_eou_120m-v1)). It can replace both the 0.6B utterance STT and a separate semantic endpoint detector for English.
- **Pipecat Smart Turn v3** is an 8M-parameter Whisper-Tiny-derived audio endpoint classifier, 8 MB INT8 CPU / 32 MB FP32 GPU, 23 languages, BSD-2-Clause. It runs after a VAD pause, examines up to the last 8 seconds including prosody, and reports around 65 ms on Pipecat's standard CPU instance (project measurement) ([official repository](https://github.com/pipecat-ai/smart-turn)). Keep Silero, lower its silence trigger to about 200 ms, then let Smart Turn decide complete/incomplete with a hard maximum wait.

The second design is easiest to integrate into m8 without changing STT. Stream partial STT for captions but commit the player turn only when EOU/Smart Turn fires. Add acoustic echo cancellation and tag game/TTS playback so companion audio is not retranscribed. Support barge-in: on player speech, duck/stop TTS quickly, but retain the interrupted sentence and decide whether to resume or acknowledge.

### Full-duplex speech models

**Moshi** is the clearest open full-duplex reference: a 7B temporal model jointly processes separate user and assistant audio streams plus an inner-monologue text stream through the Mimi codec. Kyutai reports 160 ms theoretical and ~200 ms practical latency on an L4, and CC BY 4.0 weights ([official repository](https://github.com/kyutai-labs/moshi)). It is English-only, voice/personality changes require fine-tuning, and its own FAQ says small-GPU/Apple use is not currently practical. On a 24 GB card already rendering a game, it is a research alternative, not the v2 default.

OpenAI's current **GPT-Live 1** is a hosted full-duplex model that can listen and speak simultaneously and delegate reasoning/tools to a backend agent. It costs $0.05 per connected minute ($3/hour), including silence, plus backend model/tool cost ([official model page](https://developers.openai.com/api/docs/models/gpt-live-1), [cost guide](https://developers.openai.com/api/docs/guides/voice-latency-cost)). This is the cleanest hosted fallback if network latency/privacy are acceptable. GPT-Realtime-2.1/mini are turn-based speech-to-speech alternatives over WebRTC/WebSocket/SIP; current prices are on the [official pricing page](https://developers.openai.com/api/docs/pricing).

### Recommendations for a general companion stack

- First A/B **Qwen3-TTS 0.6B Base** against **Chatterbox-Turbo 350M** using the exact Kevin reference and 200 game lines. Add Chatterbox Nano CPU if GPU contention dominates; keep Breeze as the high-steerability/non-commercial quality arm.
- Score TTFA p50/p95, RTF, peak/resident VRAM, WER on names/numbers, speaker similarity, direction adherence, and failure rate; do not choose from demos.
- Keep Silero, add CPU Smart Turn v3, and stream partial Parakeet results; alternatively trial Parakeet Realtime EOU 120M as one integrated English STT/EOU model.
- Implement echo cancellation, TTS playback tagging, barge-in, and sentence-level cancellation before pursuing a full-duplex foundation model.
- Treat Moshi and hosted GPT-Live as experimental/fallback paths, not as replacements for the game-specific decision controller.

## 4. Serving the whole stack on one 24 GB consumer GPU

### A workable memory and scheduling layout

The m8 README's published setup used roughly 25 GB across three servers on a 32 GB RTX 5090 ([m8 README](https://github.com/chasmlol/m8#setup-as-i-ran-it)). Separately, the task brief reports 21.6 GB after moving from the 12B VLM to the 9B on a 3090 Ti. Those are different configurations and should not be merged into one benchmark.

A safer v2 target is **≤16–18 GB steady CUDA allocation**, leaving 6–8 GB for the game's render targets/assets, transient model workspaces, and driver/display use:

| Resident component | Proposed placement | Planning allocation |
|---|---|---:|
| Qwen3.5-9B Q4_K_M + mmproj | GPU, llama.cpp | 5.3 + 0.88 GB weights; plan 7–9 GB including KV/compute |
| Qwen3-TTS 0.6B BF16 | GPU only while speaking, or resident | ~2.7 GB measured optimized path; plan 3–4 GB |
| Laya/Julia decision | CPU | ~0.45/0.17 GB Q8 file plus runtime |
| Parakeet TDT int8 or EOU 120M | CPU (sherpa/ONNX/NeMo-compatible runtime) | system RAM; measure CPU load |
| Silero + Smart Turn | CPU | ~2 MB + 8 MB INT8 weights |
| Headroom for game/driver/transients | GPU | at least 6 GB |

This is a budget, not a guarantee: allocator workspaces, context length, image embeddings, and runtime versions change peak use. Measure with the actual 3090 Ti while playing, not only on an idle desktop.

### llama.cpp router mode and model sharing

Current llama.cpp **router mode** starts when `llama-server` is launched without a model. It discovers cached/directory/preset models, spawns/forwards to model instances, autoloads by the request's `model`, and evicts/sleeps according to policy ([server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#using-multiple-models)). It simplifies ports and lifecycle; it does **not** magically co-reside arbitrary models in 24 GB or share their weights. Each loaded model is effectively its own child instance, and unloading destroys its prompt cache.

Sharing a base between decision and dialogue is theoretically attractive but not available for the stated pair: Kev uses **Qwen3.5-4B-Base**, while the dialogue VLM is Qwen3.5-9B post-trained. Even if both used the exact same 4B base, a native decision model needs its pointer/candidate head and GGUF decision metadata, while chat needs an LM head and a different serving route. llama.cpp can load multiple LoRAs, but router child models do not deduplicate base tensors across processes, and swapping adapters can invalidate KV assumptions. Treat “one shared base, two heads” as a custom-runtime engineering project; do not budget v2 around it.

If memory is the primary goal, the better simplification is a CPU Laya/Julia policy plus one GPU VLM. If quality requires Kev, Q8 is 4.8 GB and competes directly with the game; try Q4 and CPU/GPU layer split, or run Kev remotely/CPU-side and compare end-to-end latency.

### Protecting frame rate

- **Avoid simultaneous heavy kernels.** Decision should be CPU. Queue VLM vision and TTS so their GPU prefills do not overlap a frame-critical moment. TTS streaming decode can run between chunks; vision is lowest priority and cancellable.
- **Budget by peak, not file size.** Cap LLM context (the companion does not need 262k), quantize KV if evaluation allows it, use one parallel slot, and avoid oversized CUDA graphs. Breeze's fast path alone can reserve ~14.4 GiB.
- **Backpressure.** One active vision request, one dialogue generation, one TTS stream. Coalesce repeated state events and drop stale frames. The game loop must never await model HTTP.
- **Measure frametime p95/p99.** Average FPS hides a 200 ms CUDA stall. Test combat, image prefill, TTS start, and simultaneous player speech.
- **MPS is an experiment, not a real-time guarantee.** NVIDIA says MPS reduces context switching and offers memory/SM partitioning plus coarse client priorities, but priority is not preemptive and does not create hard real-time scheduling ([MPS overview](https://docs.nvidia.com/deploy/mps/latest/index.html), [priority caveat](https://developer.nvidia.com/blog/nvidia-cuda-toolkit-12-2-unleashes-powerful-features-for-boosting-applications/)). On Windows display/game workloads, MPS may not be the deployable route; benchmark WSL/Linux model processes and the native game carefully.
- **Prefer process consolidation only when the runtime supports it.** Separate CUDA processes each pay context/runtime allocations. MPS can share scheduling resources, but a single inference process with explicit streams/queues is easier to control. Router mode still uses child processes.

### Quantization priorities

1. Quantize the 9B LLM weights to Q4_K_M; keep the 880 MB vision projector at BF16 initially. Compare Q5 only if dialogue/vision regressions are visible.
2. Keep KV modest through an 8k–16k active context; test Q8 KV before lower precision because visual/persona consistency matters more than maximum context.
3. Quantize TTS only after measuring speaker similarity and WER. A 0.6B BF16 TTS is already small enough that quantization risk may not be worth it.
4. Q8/INT8 decision and STT are usually low-risk, but recalibrate decision probabilities after quantization; OpenJev's own GGUF study found 3–4% of individual answers changed even when aggregate accuracy moved little ([format evaluation](https://huggingface.co/openjev/openjev#formats)).

### Local and hosted cost per hour

At the 3090 Ti reference board's 450 W graphics power plus roughly 100–150 W for the rest of the PC, a conservative 0.55–0.60 kW active draw costs **$0.10–$0.11 per play-hour** at the EIA's forecast 2026 US residential average of 18.2 cents/kWh ([NVIDIA specification](https://www.nvidia.com/es-la/geforce/graphics-cards/30-series/rtx-3090-3090ti/), [EIA forecast](https://www.eia.gov/outlooks/steo/archives/may26.pdf)). Add hardware amortization: a $1,000 GPU over 5,000 used hours is $0.20/hour, making a planning total of **$0.30–$0.31/hour** before the rest of the PC. Marginal cost is the electricity figure if the hardware is already owned. Actual gaming/model duty cycle may be lower than the 450 W maximum; log wall power for a better number.

Hosted examples, excluding ordinary internet access:

- **GPT-Live 1:** exactly **$3.00/hour connected**, including silence, plus delegated backend reasoning/tools.
- **GPT-Realtime-2.1 mini:** with a sample hour containing 10 minutes of player speech and 10 minutes of companion speech, audio alone is about **$0.30/hour** (input: 6,000 audio tokens × $10/M; output: 12,000 × $20/M), before text/image/context and optional transcription. Full 2.1 is about **$0.96/hour** on the same audio assumption. The token conversion is 1 input token/100 ms and 1 output token/50 ms per OpenAI's [official cost guide](https://developers.openai.com/api/docs/guides/voice-latency-cost); current rates are [official pricing](https://developers.openai.com/api/docs/pricing). Long conversations resend growing context, so real bills are higher unless truncation/caching is managed.
- **GPT-Realtime-Whisper:** $0.017 per input audio minute; 10 minutes of player speech is **$0.17/hour of play** ([official model page](https://developers.openai.com/api/docs/models/gpt-realtime-whisper)).

Cloud TTFA includes capture/commit, WAN round trip, provider queue, model, and audio buffering. No provider publishes a latency that predicts a particular player's route, so **do not quote a universal cloud latency**. Measure p50/p95 from target regions. A pragmatic fallback sends only dialogue/TTS to cloud after a local timeout; action control stays local so a network outage cannot stall or mis-control the companion.

### Recommendations for a general companion stack

- Target CPU Julia/Laya + GPU Qwen3.5-9B Q4 VLM + GPU Qwen3-TTS 0.6B, with VAD/STT/Smart Turn on CPU.
- Keep at least 6 GB of GPU headroom for the game and transient allocations; set hard concurrency/backpressure limits.
- Use llama.cpp router mode for lifecycle convenience, not for weight sharing. Keep the frequently used VLM resident; do not sleep it if prefix-cache latency matters.
- Schedule vision as cancellable background work and TTS/dialogue at lower/cooperative priority; validate p99 frame time in real combat.
- Keep local action control under all fallback modes. Use hosted full-duplex voice only as an opt-in quality/reliability path with explicit privacy and cost controls.

## Candidate component table

Latency numbers are not directly comparable unless hardware and input are shown. “NR” means no reliable primary-source figure located.

| Role | Model | Size / reported memory | Reported latency / throughput | Licence | Companion-stack notes |
|---|---|---|---|---|---|
| Decision | Julia-1 | 144.3M; Q8 GGUF 168 MB | 3 ms/question on RTX PRO 6000 (ggml) | Apache-2.0 | CPU-first candidate; private training pipeline; 2–20 options native |
| Decision | Laya | 421M; Q8 449 MB | 5 ms/question on RTX PRO 6000 (ggml) | Apache-2.0 | Strong CPU/edge candidate; 512-token English default budget |
| Decision | Kev-4B | 4B; Q8 4.8 GB | 12 ms short question on RTX PRO 6000; **m8: 120–140 ms/~800-token call on 3090 Ti** | Apache-2.0 | Best documented continuation training; expensive if repeatedly prefilling |
| Decision | lev | 4B; Q4 3.03 GB, Q8 4.48 GB | 69 ms short call on H100; 1–8 questions roughly flat | Apache-2.0 adapter; review dataset terms | Rich label/candidate readout; English; game tune required |
| Decision/Vision | OpenJev | 27B; GGUF Q4 19.4 GB (ggml card), source card reports other Q4 build 16.5 GB | ~80 ms short text, ~210 ms web decision on H100 FP8 | CC BY-NC 4.0 | Does not fit the desired stack; GGUF build text-only in source evaluation |
| Dialogue + vision | Qwen3.5-9B | 9B; HauhauCS Q4 5.3 GB + 0.88 GB mmproj | **m8: 45 ms first token cached, 120 tok/s; ~2 s/1080p frame** | Apache-2.0 base/derivative label | Preferred ≤9B model; uncensoring claims require independent evaluation |
| Dialogue + vision | Gemma4-12B HauhauCS | 12B QAT Q4; exact resident VRAM depends runtime | m8 baseline; 12B prevented 24 GB full-stack fit | Gemma licence | Quality arm for 32 GB, outside requested ≤9B target |
| TTS clone | Qwen3-TTS 0.6B Base | ~0.6B talker; third-party BF16 path 2.675 GB VRAM | 97 ms first packet vendor claim; third-party RTF 0.13 | Apache-2.0 | Best memory-first v2 candidate; validate real clone TTFA and control |
| TTS clone/expressive | Chatterbox Turbo / Nano | 350M / 110M; self-host VRAM NR | Nano: 3× realtime on 8 CPU cores (vendor); Turbo TTFA NR | MIT | Clone + native non-verbal tags; strongest small commercial candidate |
| TTS clone/direction | Breeze TTS 2 | ~3B; 7.7 GiB eager, 14.4 GiB `--fast-all` | <40 ms TTFA, RTF 0.32 on H100 (vendor) | Research/non-commercial weights/outputs | Best feature match, largest v2 memory pressure |
| TTS expressive | Orpheus | 3B; community ~7–15 GB, runtime-dependent (**unverified**) | ~200 ms stream, ~100 ms with input streaming (vendor) | Verify checkpoint; repo Apache-2.0 | Expressive tags; heavy; original smaller sizes were not ready |
| TTS dialogue | Dia | 1.6B; ~4.4 GB bf16/fp16 on 4090 | 1.3–2.2× realtime on 4090 | Apache-2.0 | Excellent nonverbals/dialogue, awkward for <5 s fragments |
| TTS clone | F5-TTS | ~336M; community ~3 GB (**unverified**) | TRT L20: 253 ms avg, RTF 0.0394 | CC BY-NC 4.0 weights | Quality research arm; non-commercial and not natively stream-first |
| TTS clone/control | Fish S2-Pro | ~4B + decoder; ≥24 GB | H200 SGLang: RTF 0.195, ~100 ms TTFA (vendor) | Fish Audio Research Licence (S2-Pro) | Cannot co-reside; rich inline controls |
| TTS clone/control | Higgs Audio v3 | 4B; community 11 GB bf16 / 3.5 GB 4-bit (**unverified**) | NR comparable | Research/non-commercial | Too heavy/licence-limited for default |
| TTS on-device | NeuTTS Air/Nano | Air ~748M; Q4 community test ~3.3 GB | Community warm TTFA ~434 ms; not primary | Per-checkpoint Apache-2.0 or NeuTTS Open 1.0 | GGUF streaming and cloning; limited emotion control |
| TTS fallback | Kokoro-82M | 82M; community ~0.5–0.7 GB | Community 3090 RTF ~0.02; no upstream standard | Apache-2.0 | Very fast preset voices; no arbitrary zero-shot cloning |
| TTS CPU | Kyutai Pocket TTS | Lightweight; exact selected config NR | CPU-oriented streaming; NR comparable | CC BY 4.0 | Promising way to protect game GPU; clone with consent |
| STT | Parakeet TDT 0.6B v2 int8 | 0.6B; CPU/sherpa runtime in m8 | End-of-utterance batch latency depends utterance/runtime | CC BY 4.0 family; verify exact artifact | Current accurate utterance STT; keep if Smart Turn is added |
| Streaming STT/EOU | Parakeet Realtime EOU 120M v1 | 120M | 80–160 ms algorithmic latency | NVIDIA Open Model License | English; integrated EOU; no punctuation/caps |
| VAD | Silero VAD | ~2 MB in m8 | Frame-scale CPU inference; exact config-dependent | MIT (code/model repo) | Keep; detects speech, not semantic turn completion |
| End-of-turn | Smart Turn v3 | 8M; 8 MB INT8 CPU / 32 MB FP32 | ~65 ms standard Pipecat CPU instance | BSD-2-Clause | Best low-cost addition; 23 languages; consumes up to 8 s audio window |
| Full duplex | Moshi | 7B temporal model + Mimi/depth model | 160 ms theoretical, ~200 ms practical on L4 | CC BY 4.0 | English; personality needs tuning; poor one-card fit with game |
| Hosted full duplex | OpenAI GPT-Live 1 | Hosted | Network/region dependent; full duplex | API terms | $3/hour connected + backend; excellent fallback, not local control |
| Hosted speech-to-speech | GPT-Realtime-2.1 mini | Hosted | Network/region dependent | API terms | Sample 10 min in/10 min out ≈$0.30 audio/hour + context/transcription |

## Proposed v2 experiment order

1. **Policy latency first:** add one combined action+speak call; benchmark Julia, Laya, Kev Q4/Q8 on 1,000 replayed m8 states. Select by confident-error/coverage and p95, not average accuracy alone.
2. **TTS bake-off:** Qwen3-TTS 0.6B, Chatterbox-Turbo (plus Nano CPU), and existing Breeze on the same 200 lines/reference. Record peak VRAM while the game and VLM are resident.
3. **Turn-taking:** add Smart Turn v3 behind 200 ms Silero pauses; compare false interruption, end-of-turn delay, and barge-in success against the current silence timer. Then test Parakeet Realtime EOU as an integrated replacement.
4. **Persona:** build the scripted SFT set and blind preference set; train a small LoRA, then DPO. Lock a 30-minute replay suite for repetition, brevity, character consistency, vision grounding, and memory.
5. **Integrated soak:** one-hour combat sessions with p50/p95/p99 game frametime, model latency, VRAM peak, dropped/stale jobs, audio underruns, action errors, and estimated $/hour. Only after this should MPS, TTS quantization, or a shared-base custom runtime be attempted.
