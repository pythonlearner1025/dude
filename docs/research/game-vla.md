# Pixel-to-keyboard/mouse game policies: the state of the art

**Research date:** 29 October 2026. **Question:** could Kev become a general, high-frequency
"system 1" (a few billion parameters at most) that takes game frames plus a text instruction
(possibly empty) and outputs human keyboard/mouse actions, trained with in-game reward and
driven by a large LLM "system 2"? Claims marked *self-reported* come from the authors only.

## 1. Systems

| System (org, date) | Input → output | Size, rate, hardware | Training | Text instructions | What it shows |
|---|---|---|---|---|---|
| [NitroGen](https://nitrogen.minedojo.org/) (NVIDIA/MineDojo, Dec 2025) | 256×256 frame → gamepad (sticks, buttons) | ~500M (SigLIP2 + flow-matching DiT, GR00T-style) | Behaviour cloning on 40k h from 1,000+ games; actions read from streamers' on-screen controller overlays | None | Zero-shot play across genres; up to +52% relative when fine-tuned on 30 h of a new game. Weak on mouse/keyboard-heavy games; reactive, no planning |
| [Open-P2P / Pixels2Play](https://elefant-ai.github.io/open-p2p) (Player2, Jan 2026) | frames + optional text → keyboard/mouse (≤4 keys, 2 mouse actions) | 150M–1.2B; **20 Hz on one consumer GPU** (RTX 5090) | Behaviour cloning: 8.3k h labelled human play (released) + IDM-labelled public video; text captions added afterwards by VLMs | Optional; small effect ("pick up shotgun": 5/5 with text vs 1/5 without, Doom/Quake) | Closest open match to the proposal. Novice-human level on simple games; poor at long horizons; needed to mask past actions to stop copying |
| [Lumine](https://arxiv.org/abs/2511.08892) (ByteDance Seed, Nov 2025) | 720p frames at 5 Hz → text-encoded keyboard/mouse at 30 Hz (6 chunks per step) | Qwen2-VL-7B; ~114 ms first action; **4× H20 GPUs**, W8A8 | 1,731 h Genshin play + 200 h instruction data + 15 h reasoning traces | Yes; >80% on simple tasks (collect, fight, talk, puzzle) | Finished a 5-hour storyline; zero-shot into two other games. A 2B version stopped improving after ~1,200 h; 7B kept improving. Half the errors were visual misunderstanding |
| [Game-TARS](https://arxiv.org/abs/2510.23691) (ByteDance Seed, Oct 2025) | screenshots → native keyboard/mouse, same action space for OS, web and games | Continued from Seed-VL-1.5 (proprietary); 500B tokens | Large pre-training + RL; "sparse thinking" | Yes | *Self-reported:* ~2× prior SOTA on open-world Minecraft and better than GPT-5 / Gemini 2.5 Pro / Claude 4 Sonnet on FPS benchmarks |
| [SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) (DeepMind, Nov 2025) | screen → virtual keyboard/mouse + dialogue | Gemini Flash-Lite core | Human demos, then **self-improvement: Gemini sets tasks and scores attempts**, trajectories retrain the agent | Yes, plus conversation and reasoning | Much closer to humans than SIMA 1; works in held-out games (ASKA, MineDojo). Open problems they name: precise low-level mouse/keyboard, long horizons, complex 3D scenes |
| [CombatVLA](https://arxiv.org/abs/2503.09527) (ICCV 2025) | frames → keyboard/mouse action sequences | 3B, fast "truncated action-of-thought" | Video-action pairs from an input logger | Task prompts | Boss fights in *Black Myth: Wukong*; one game |
| [MAIN-VLA](https://arxiv.org/abs/2602.02212) (Feb 2026) | frames + instruction → actions | VLM with token pruning | Abstracts instructions into primitives and frames into affordances | Yes | *Self-reported* SOTA in Minecraft and PvP shooters (Game for Peace, Valorant) |
| [GameWAM](https://arxiv.org/abs/2608.26200) (Aug 2026) | frames + task → predicted future frames **and** keyboard/mouse trajectories | Flow-matching world-action model | Synchronised gameplay + GUI trajectories | Task context | First world-action model for closed-loop gameplay; plans by imagining the next frames |

**Companions specifically (language model over a separate controller):**

| System | Brain (system 2) | Body (system 1) | Result |
|---|---|---|---|
| [PUBG Ally](https://www.alphaxiv.org/abs/2609.29837) (KRAFTON + NVIDIA ACE, 2026) | Mistral-NeMo-Minitron-2B on the player's GPU, observes through text tools, distilled from a larger teacher | Hand-built behaviour tree at tick rate | ~39k real sessions. Beta, out of 5: [combat 2.58, judgement 2.88, response speed 2.93, command execution 2.99](https://www.invenglobal.com/articles/26592/built-a-teammate-got-a-chat-partner-kraftons-first-scorecard-for-pubg-ally); conversation rated higher. Players saw "Okay" without the action. One spoken exchange: 1.62 s median on device, 3.36 s via cloud |
| [Tencent FPS agent](https://www.invenglobal.com/articles/25084/tencent-unveils-shooter-ai-agent-that-rejects-player-orders) (gamescom, Aug 2026) | VLM reads map images + text status and outputs **skill chunks** with parameters (target, place, duration) | RL-trained LSTM per skill (combat, driving, retreat…) on raycasts and engine state, simple rewards (+1 kill, −0.01/step) | Event-driven replanning; treats player orders as advice. No numbers published |

**Robotics, where the split is now standard:** [GR00T N1](https://arxiv.org/abs/2503.14734) (VLM ≈1.3B
at ~10 Hz + diffusion action head at ~120 Hz; N1.7 is 3B), Figure Helix (VLM at 7–9 Hz + small
policy at 200 Hz, linked by a latent vector), π0 / π0.5 (VLM with a flow-matching action expert).
Online RL on top of these now works: [π_RL](https://arxiv.org/abs/2510.25889) for flow VLAs, and
[Real-Time EXPO-FT](https://arxiv.org/abs/2609.18207), where a small edit policy corrects a slow
VLA from the latest frame (42% → 97% on dynamic tasks with ~10 minutes of online data).

## 2. What this says about the proposal

1. **The split is where everyone converged.** A large model decides *what*; a small fast
   policy does *how*. Games use it (PUBG Ally, Tencent) and robots use it (GR00T, Helix, π). The
   open question is the interface: text instructions (Open-P2P, Lumine), parameterised skill
   chunks (Tencent), or a learned latent (GR00T, Helix). Text lets any LLM drive the policy and is
   easy to debug, but it loses spatial detail.
2. **Keyboard/mouse from pixels works, and is the generalising choice.** SIMA 2, Game-TARS,
   Lumine and Open-P2P all use it, with no game API. The weak spots are the same everywhere:
   precise mouse control (aiming), small or far objects, and long horizons.
3. **Following simple instructions works; tactical, spatial ones are unproven.** Published
   instruction following is atomic: "pick up the shotgun", "collect", "talk to the NPC". Nothing
   shows a policy reliably doing "flank right, take cover behind the rocks, attack". That is
   the open research problem, and exactly what Kevin failed at.
4. **Size: a few billion is the right range for the body, maybe not for understanding.**
   Open-P2P (≤1.2B) and NitroGen (0.5B) run in real time on one consumer GPU. Lumine's 2B
   saturated around 1,200 hours while 7B kept improving, so compositional instructions may
   need the system 2 to break them into atomic steps the small policy can follow.
5. **RL from in-game reward is rare in games; imitation dominates.** Every pixel game policy
   above is mainly behaviour-cloned. RL shows up as SIMA 2's self-improvement (Gemini sets
   tasks and judges success), Tencent's per-skill rewards on engine state, and robotics online
   fine-tuning. For instruction-conditioned objectives, the reward has to judge "did he flank
   right and get behind the rocks": either a VLM judge (SIMA 2's way) or predicates on game
   state per instruction template (per-game work, but only at training time).
6. **Data is the real cost.** Keyboard/mouse labels can't be read from ordinary videos
   (NitroGen relied on gamepad overlays). Open-P2P needed 8.3k recorded hours plus an inverse
   dynamics model to label more. No dataset exists of a *companion following spoken orders*;
   hindsight captioning (Open-P2P, Lumine) is the cheap way to create instructions.
7. **A companion needs its own body and its own camera.** Every policy above plays *as the
   player*. Kevin would need his own render (his point of view) and his own controls, e.g. a
   second local player. Today he is an engine-driven actor with no view.
8. **PUBG Ally is the cautionary result.** A shipped, well-funded companion with a hand-built
   body still scored below 3/5 on every gameplay measure while conversation scored well, the
   same split as our playtests. The body is the bottleneck.

## 3. Starting points we could use

- **Open-P2P:** open data (8.3k h), code and 150M–1.2B checkpoints with optional text input, 20 Hz
  on a consumer GPU. The natural base for a learned Kev.
- **NitroGen:** open weights and a wrapper that exposes commercial games as a Gymnasium API;
  gamepad only, no text.
- **OpenCE Halo** (our build): open engine, so we can render a second point of view, read exact
  state for rewards, and run several instances in parallel. Commercial games only run in real
  time.

## 4. Can a Jev-style decision model learn what we want?

**What Kev actually is.** [Kev-4B](https://huggingface.co/jaredpalmer/kev-4b) is a general decision
model by Jared Palmer, not a game model: a LoRA (rank 16) on a frozen Qwen3.5-4B-Base with a pointer
head that scores each option against the question. It was trained on ~35k records (public
classification sets, policy rules, finance complaints, code review), with no game data. m8 uses it
zero-shot. Its card: 0.69 vs Jev's 0.76 on 14 held-out datasets, MMLU-Pro 0.57 vs 0.84, date
arithmetic 0.65; "largest gains are in-distribution"; option order can change answers.

**Generalisation evidence.** [S1MB](https://huggingface.co/blog/hotchpotch/system-one-mosaic-benchmark)
has six probes with freely varied instructions and contexts (task average): Jev 1.13 96, Open-Jev-9B 86,
kev-9b 85, **kev-4b 78**, OpenJev-2B 64, kev-0.8b 51. A 400M model trained on the benchmark's own
domains ranks 2nd overall but scores 54 on the probes: small models learn their training domain,
and following new instructions grows with size. [Releasing the Inner Jev](https://arxiv.org/abs/2610.17205)
(Oct 2026) finds an untrained open LLM read through its answer-letter logits already near Jev
(Gemma 4 31B: 79.6 vs 80.1), and LoRA + head fine-tuning passes it (84.4): decision quality is
mostly the base model's understanding; the head adds speed and calibration.

**For us.** A decision model can learn "which offered action and target fits this order in this
state" if fine-tuned on labelled game decisions (Kev's code is open: github.com/jaredpalmer/kev).
It cannot do what isn't an option (no action for "flank right"), plan sequences, remember, output
continuous control, or (Kev) see images. Its role is a fast selector/router, not a body.

## 5. Computer-use models

- **Standard Intelligence [FDM-1](https://si.inc/posts/fdm1/)** is the nearest thing to a general
  human-like action model: trained on 11M hours of screen video labelled by an inverse dynamics
  model (itself trained on 40k contractor hours), keyboard/mouse tokens from 30 fps video, 11 ms
  capture-to-action, and fine-tuned to steer a real car with under an hour of data. No language
  model transfer (so no text instructions), size undisclosed, **weights not released**.
- **Open computer-use agents** (UI-TARS-1.5-7B, OpenCUA-7B/32B/72B, GUI-Owl-7B, EvoCUA-8B/32B at
  56.7% OSWorld, Fara-7B) take a screenshot and emit one click/type/hotkey per step, seconds per
  step, 15-100 steps per task. They are not real-time controllers (no continuous mouse, no aiming)
  and are trained on desktop GUIs, not 3D games. Useful pieces: their **grounding** (pointing at
  "the big rock" in a screenshot, which the engine can turn into a world position).
- **Best open fits by role:** body → Open-P2P (open, text-conditioned, keyboard/mouse at 20 Hz);
  game-video labelling → [Reka IDM](https://huggingface.co/RekaAI/Reka-Inverse-Dynamics-Model) /
  VPT; fast selector → a game-fine-tuned Kev-4B/9B or Open-Jev-9B; pointing → a GUI grounding model.
