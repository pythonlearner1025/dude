# Causal data and cheap tokens unlock Kevin's body

You are right in substance. Nothing published says a ~12B vision-language model cannot be trained to watch 10-20 fps video and emit language-conditioned keyboard and mouse actions as asynchronous tool calls. A 7B Qwen2-VL (Lumine) already plays a 3D game from 5 Hz video, emitting 30 Hz actions, with **over 80% success on simple instructions**. Its 7B kept improving with data where a 2B degraded ([Lumine](https://arxiv.org/html/2511.08892)). The gap is not model size or a missing invention. Six ordinary ingredients are missing, and each has prior art: (1) instruction-action data that is causal, meaning the order comes before the action, and counterfactual, meaning the same scene with different orders leads to different play, across many environments; (2) a video front end that spends **16-32 tokens per frame instead of the 70-1,200** that VLMs spend today, trained on the action objective; (3) an action interface in which each tool call carries about one second of actions decoded by a fast head, not one keystroke per token; (4) training that stops the backbone from ignoring language and keeps it able to talk; (5) closed-loop correction, meaning DAgger plus RL with verifiable rewards; (6) training and serving throughput. Your target is ahead of shipped products: Gemini's Live API takes **1 frame per second**, and Google's robotics streaming API supports **only blocking function calls** ([Vertex Live API](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/send-audio-video-streams); [Gemini Robotics streaming](https://ai.google.dev/gemini-api/docs/robotics-streaming)). It is not ahead of the parts list. For Kevin, OpenCE turns the most expensive ingredient in the prior art, causal language-action data, into the cheapest: a teacher bot that reads exact engine state can label every frame with true inputs and an instruction issued before the action, at no labelling cost. My estimate for the path below is **about 2,000-4,700 H100-hours (about $4-19k of compute; $10-35k all-in with reruns and human play)**, a quarter or less of Lumine's ~20.7k H100-hours. Cutting tokens per frame 40-75× (from ~1,200 to 16-32) more than pays for 2-4× more frames: tokens per second of gameplay still fall 8-30×. On the 3090 Ti, a 4-bit 12B taking 10 fps and emitting action chunks at 5 Hz fits the compute budget (est.). It does not fit in memory beside the 9 GB Breeze TTS unless 2-3 GB is freed. A dual system, Gemma 12B issuing orders to a fine-tuned Open-P2P-600M body, fits today.

## Six missing ingredients, none of them model size

The case that capacity is enough rests on several results. Lumine (Qwen2-VL-7B) finished a five-hour storyline in Genshin Impact. Its 2B variant's benchmark scores *degraded* past about 1,200 h of data while the 7B kept improving ([Lumine](https://arxiv.org/html/2511.08892)). JARVIS-VLA, also Qwen2-VL-7B, reaches **0.70-0.95 success** across Minecraft mine/kill/craft/smelt task groups ([JARVIS-VLA](https://arxiv.org/html/2503.16365)). A 3B robotics VLA computes a 50-step (~1 s) action chunk in ~100-140 ms and executes it asynchronously while the next one is computed ([PI RTC](https://www.pi.website/research/real_time_chunking)). Nothing here suggests a 12B ceiling.

The skeptic's best point is that nobody has published the exact system you describe. **No published agent feeds a 7-12B VLM at 10-20 fps.** StreamingVLM, a Qwen2.5-VL-7B fine-tune, manages up to **8 fps on an H100** ([StreamingVLM](https://arxiv.org/html/2510.09608v1)). Lumine needed **four H20 GPUs** to reach ~114 ms per 5 Hz step at ~1,200 visual tokens per frame ([Lumine](https://arxiv.org/html/2511.08892)). NVIDIA's 14B DreamZero needs **two GB200s for 7 Hz** ([DreamZero](https://arxiv.org/html/2602.15922)). Your own zero-shot test points the same way. Open-P2P-600M ran Kevin at 19.6 Hz on the 3090 Ti, but under "move forward" it **stood still for all 60 seconds and pressed arrow keys Halo does not bind** ([local test](../reports/p2p-halo-zero-shot.md)). That is the language-ignoring and action-space mismatch problem in miniature.

So these are engineering and data gaps, not capability limits. Each ingredient below is missing from open models today, and each has a demonstrated fix.

| Missing ingredient | Evidence it is missing | Demonstrated fix | Cost for Kevin |
|---|---|---|---|
| 1. Causal, counterfactual instruction-action data across environments | No public FPS dataset pairs instructions issued *before* actions with true keyboard/mouse at 10-20 fps. Open-P2P's captions are hindsight from an unnamed VLM, with unknown coverage ([Open-P2P](https://arxiv.org/html/2601.04575v2)). VLAs at over 90% fall to 0% under perturbation and ignore junk instructions ([LIBERO-PRO](https://arxiv.org/abs/2510.03827)) | Setter-solver play (SIMA), category-anchored relabelling (Lumine), privileged scripted teachers (LBC, VIMA) | Lowest: OpenCE gives exact state, true inputs and forkable states |
| 2. A low-token video front end trained on actions | VLMs spend 70-1,200 tokens per frame; only policies trained from scratch reach 1-5 tokens per frame | Learned resamplers (Apollo, MiniCPM-V), encoders trained jointly with actions (Open-P2P, FDM-1) | Moderate: one resampler stage, plus an unmeasured risk to aiming detail |
| 3. Chunked, latency-aware async action output | Per-frame action tokens collapse into copying at 20-50 Hz ([FAST](https://arxiv.org/html/2501.09747)); Google's Live API for robotics is blocking-only | Flow/regression action experts, real-time chunking, training with simulated delays | Low: known recipes |
| 4. Training that keeps the backbone listening and talking | Naive action heads degrade VLM semantics; SIMA 2 lost 25.5% relative on AIME ([SIMA 2](https://arxiv.org/html/2512.04797)) | Frozen or gradient-insulated backbone, plus vision-language co-training | Low: ~20% extra compute per step |
| 5. Closed-loop correction | Behaviour cloning compounds errors; RL from 0% success stays at 0% ([SimpleVLA-RL](https://arxiv.org/html/2509.09674)) | DAgger with a privileged teacher; GRPO/PPO on engine-verified rewards | Moderate: needs parallel game instances |
| 6. Throughput | 7B VLM agents need multi-GPU serving at 5 Hz | Token cuts, 4-bit weights, bounded KV cache, parallel action head | The design choice that sets every cost |

## Language-action alignment needs causal labels more than hours

The prior art agrees more than its headline numbers suggest. Every system that follows instructions well rests on a **large action-only prior plus a small, carefully made instruction slice**. The instruction slice is **~0.1% of frames for STEVE-1, ~12% of hours for Lumine, and 100% for SIMA**. What separates strong from weak instruction following is how that slice was made, not its size.

| System | Backbone | Action data | Instruction data and how it was made | Instruction result |
|---|---|---|---|---|
| Lumine | Qwen2-VL-7B | 1,731 h, one game | **200 h** (~11.5%): humans tagged 38 activity types on 165 h, a 2B classifier spread the tags, GPT-4.1 wrote and verified the text; plus 15 h of reasoning traces | **>80%** on simple tasks, +61% over base ([arXiv](https://arxiv.org/html/2511.08892)) |
| Game-TARS | Seed-VL-1.5 MoE, 2.5B active; Dense variant on Qwen2.5-VL-7B | 526B tokens of pre-training, ~20k game hours | **127B tokens of human think-aloud** play (≥3 thoughts per minute) plus task prompts | Minecraft 72%; other games' data lifted it **42% → 65%** ([arXiv](https://arxiv.org/html/2510.23691)) |
| UI-TARS-2 | 230B MoE, 23B active | undisclosed | think-aloud plus humans correcting live rollouts; multi-turn RL | 15-game suite **44.3 → 59.8** from RL, ~60% of human ([arXiv](https://arxiv.org/html/2509.02544)) |
| JARVIS-VLA | Qwen2-VL-7B | >7.4M frames (~100 h est.) plus 6.4M GUI entries | task names, **≥100 trajectories per task**; plus 277k knowledge QA, 20k VQA, **404k spatial-grounding points** | 0.70-0.95; beats imitation-only with 21% of the trajectories ([arXiv](https://arxiv.org/html/2503.16365)) |
| OpenCUA-32B / Fara-7B | Qwen2.5-VL | none | **22,625 human** / **145,603 synthetic verified** trajectories (~$1 each) | OSWorld-Verified **3% → 34.8%** ([OpenCUA](https://opencua.xlang.ai/)); WebVoyager 73.5 ([Fara](https://arxiv.org/html/2511.19663)) |
| Open-P2P | 150M-1.2B, from scratch | 8.3k h, 40+ games | unknown fraction; commercial-VLM hindsight goals | button test **~20% → ~80%**; "only simple instructions similar to the training set" ([project](https://elefant-ai.github.io/open-p2p)) |
| NitroGen | 500M | 40k h of gamepad play, 1,000+ games | none; language encoder deliberately removed | 30 h of a new game: **+52% combat, +5% game-specific** ([arXiv](https://arxiv.org/html/2601.02427)) |
| SIMA 1 / 2 | SIMA 2: Gemini Flash-Lite | not separated | all of it: live setter-solver pairs, hindsight self-annotation, Gemini relabelling, then self-improvement | SIMA 1 on No Man's Sky **34% vs 11%** without language (humans 60%); SIMA 2 ~2× SIMA 1 ([SIMA 1](https://arxiv.org/html/2404.10179v3), [SIMA 2](https://arxiv.org/html/2512.04797)) |
| VPT | 0.5B | 70k h labelled by an IDM | 17k h of closed captions | weak steering only ([arXiv](https://arxiv.org/abs/2206.11795)) |
| STEVE-1 | VPT 0.5B | ~750 h (est.) | **2,000 human + 8,000 GPT pairs** from <30 min of play, via visual-goal relabelling | 12/13 tasks for **$60 of compute** ([arXiv](https://arxiv.org/html/2306.00937)) |
| FDM-1 | undisclosed, no language-model initialisation | **11M h** labelled by an IDM trained on 40k contractor hours | 1.25T transcript tokens "for instruction tuning downstream"; no instruction interface published | none published; <1 h of data to steer a real car ([si.inc](https://si.inc/posts/fdm1/)) |

Robotics shows the same pattern. Generalist VLAs train on **10²-10⁴ hours** of teleoperation. Examples: Helix ~500 h, π0.5 ~400 h on the target robot with **97.6%** of first-phase examples from elsewhere, π0 over 10,000 h. Language comes mostly from **hindsight VLM labels on short segments** or ~2-second human segment labels ([Helix](https://www.figure.ai/news/helix); [π0.5](https://arxiv.org/html/2504.16054); [π0](https://arxiv.org/html/2410.24164)). DIAL crowd-labelled a small seed (**3.5-7% of 80,000 demos**, depending on how it is counted), used it to train a relabeller for the rest, and gained **over 41% on 60 novel instructions** ([DIAL](https://arxiv.org/pdf/2211.11736)). Per-task adaptation runs from **5 h for simple tasks to 100+ h for the hardest** in π0. Gemini Robotics On-Device needs **50-100 demonstrations** ([π0](https://arxiv.org/html/2410.24164); [DeepMind](https://deepmind.google/discover/blog/gemini-robotics-on-device-brings-ai-to-local-robotic-devices/)).

### Five rules for language-action data

**Rule 1: the instruction slice can be small if the action prior is large, but the prior must exist.** GRIF's language-conditioned policy scored **0 on new instructions** without its 47k unlabelled trajectories ([GRIF](https://arxiv.org/abs/2307.00117)).

**Rule 2: label provenance beats label volume.** Lumine's human-anchored pipeline reached >80%; Open-P2P's raw VLM captions on a small model managed only simple prompts. Model size is confounded there. The robotics comparison is cleaner. NILS's anchored ensemble grounded **0.66 vs 0.16 for raw Gemini 1.5**. On a real robot its labels gave **63% success vs 60% with ground-truth labels**, at ~$200 instead of ~$5,000 for crowdsourcing ([NILS](https://arxiv.org/abs/2410.17772)). SIMA's authors call setter-solver data, where the instruction precedes the action, "more causally correct" than hindsight labels ([SIMA 2](https://arxiv.org/html/2512.04797)).

**Rule 3: language must be counterfactually necessary, or the policy learns to ignore it.** Physical Intelligence found π0 "often ignores the language instructions" ([FAST](https://arxiv.org/html/2501.09747)). Freezing the VLM in GR00T N1.5 raised real-robot **language following from 46.6% to 93.3%** ([GR00T N1.5](https://research.nvidia.com/labs/gear/gr00t-n1_5/)). Removing web data from π0.5 barely mattered in-distribution but **significantly hurt out-of-distribution language following** ([π0.5](https://arxiv.org/html/2504.16054)).

**Rule 4: diversity beats repetition.** Robot generalization follows a power law in environments and objects. **32 environments × 50 demos reached ~90%** in new environments ([scaling laws](https://arxiv.org/html/2410.18647v3)). Removing π0.7's most diverse 20% of data hurt more than removing a random 20% ([π0.7](https://arxiv.org/html/2604.15483v1)).

**Rule 5: generic skills transfer across games; game-specific mechanics do not.** Game-TARS gained 23 points from other games' data, and SIMA 1's multi-game generalist beat specialists by **67%**. NitroGen's pre-training lifted game-specific tasks by only **5%**. Lumine's zero-shot runs failed on exactly the local conventions: it pressed E instead of F, misread HUD-less scenes and used Genshin vocabulary in another game ([Lumine](https://arxiv.org/html/2511.08892)).

Lumine's emergence thresholds give the best skill-hour guide for one game and a 7B VLM: **object interaction under 100 h, combat ~1,000 h, navigation and mechanics over 1,800 h**.

### Two cheaper routes: inverse dynamics models and synthetic trajectories

FDM-1 and VPT show that **inverse dynamics models (IDMs) scale action labels cheaply**. VPT found ~100 h of contractor data (~$2,000) enough for a useful IDM, with **90.6% keypress accuracy** when trained on 1,962 h ([VPT](https://arxiv.org/abs/2206.11795)). D2E's generalist 1B IDM cost about **192 H100-hours (~$800)**, but reaches only **47.75% keyboard accuracy zero-shot on Battlefield 6** ([D2E](https://arxiv.org/abs/2510.05684)). IDM labels on other people's video help coarse skills and not fine control. D2E's pseudo-labels raised navigation (75.3% → 83.3%) and lowered manipulation (96.6% → 92.2%). Open-P2P's IDM-labelled video lowered test loss, but human raters did not prefer the resulting play ([Open-P2P](https://arxiv.org/html/2601.04575v2)). For Kevin, logging true inputs in OpenCE makes an IDM unnecessary except for mining YouTube Halo footage.

Computer-use fine-tunes add one more benchmark: a Qwen VLM goes from near-zero to useful on **10⁴-10⁵ instruction-labelled trajectories**, and synthetic trajectories checked by verifiers cost about **$1 each** ([Fara](https://arxiv.org/html/2511.19663)).

## A 10-20 fps video head means 16-32 tokens per frame

Turning an image VLM into a 10-20 fps video model is mostly a token-budget problem. Default VLM tokenization makes it impossible on one consumer GPU. Learned compression makes it routine.

| System | Tokens per frame | Frame rate |
|---|---|---|
| Lumine (Qwen2-VL, 720p) | ~1,200 | 5 Hz, on 4×H20 |
| Gemini 2.x default / low | 258 / 66 | 1 fps default ([docs](https://ai.google.dev/gemini-api/docs/video-understanding)) |
| Gemini 3 video, low-medium / high | 70 / 280 | ([docs](https://ai.google.dev/gemini-api/docs/media-resolution)) |
| NitroGen (SigLIP 2, 256 px) | 256 | one frame of context |
| Qwen3-VL at 448 px / 224 px (est. from config) | ~98 / ~24.5 | 2 fps default ([config](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/blob/main/config.json)) |
| Apollo's optimum for video QA | 8-32 | 2 fps ([Apollo](https://arxiv.org/html/2412.10360v1)) |
| MiniCPM-V 4.5 3D-resampler | ~10.7 | "up to 10 fps" ([card](https://huggingface.co/openbmb/MiniCPM-V-4_5)) |
| VideoLLM-online (8B) | 10 | **5-10 fps on an RTX 3090** ([GitHub](https://github.com/showlab/videollm-online)) |
| FDM-1 (est. from "~2 h of 30 fps in 1M tokens") | ~5 | 30 fps ([si.inc](https://si.inc/posts/fdm1)) |
| Open-P2P / StreamMind | 1 | 20 Hz / up to 100 fps ([StreamMind](https://arxiv.org/html/2503.06220v2)) |

Compression to 1-10 tokens per frame is proven only when **the encoder is trained jointly with the action or event objective** (Open-P2P, FDM-1, StreamMind). Generic VLM features pooled to 10 tokens per frame, as in VideoLLM-online, are shown only for narration and event timing, not fine control. **No published study measures game-action accuracy against tokens per frame for a VLM agent.** That gap is real, and Kevin's pilot should close it.

### The video head design

The design that fits the evidence is a **slow-fast front end**. The fast stream uses the existing SigLIP2 ViT at 224-256 px and a Perceiver resampler, which Apollo found the best resampler (55.5 vs 53.2 for pooling). It compresses each two-frame group to **16-32 tokens per frame at 10-20 fps**. The slow stream takes one higher-resolution keyframe per second (~100-250 tokens) to read HUD, ammo and distant enemies. LLaVA-Video's slow/fast pooling and F-16's per-second compression of 16 fps video are the direct precedents. F-16 beat GPT-4o and Gemini-1.5-Pro on high-speed sports analysis ([LLaVA-Video](https://arxiv.org/html/2410.02713); [F-16](https://arxiv.org/abs/2503.13956)).

The resolution matches what reflex policies already use: Open-P2P 192 px, NitroGen 256 px, VPT 128 px. Small, far targets are the known weak spot, so the 4/16/64-token ablation is the experiment that matters.

### Training requirements for the video head

The training cost of the video head is small, because **you adapt video ability rather than pre-train it**. Qwen3-VL already spent ~2T tokens across stages ([Qwen3-VL](https://arxiv.org/abs/2511.21631)). Published adaptation recipes come in three cost tiers:

| Tier | Recipe | Compute |
|---|---|---|
| Cheap | Frozen encoder + small trainable extractor (StreamMind) | **19 h on 8 A100s** |
| Middle | Full streaming SFT on ~1M samples (StreamingVLM) | **~3,100 H100-hours** |
| Expensive | Lumine's history pre-training | **19,008 H100-hours** |

Every source that tested unfreezing found it helps, and order matters. Apollo's progressive unfreezing beat one-stage training **59.2 vs 48.7**. Training the encoder while the LLM was also unfrozen on mixed data "significantly hurts". Apollo also needed **10-14% text data** in the mix ([Apollo](https://arxiv.org/html/2412.10360v1)). Open-P2P's jointly trained image tokenizer "consistently" lowered perplexity ([Open-P2P](https://arxiv.org/abs/2601.04575)).

So the sequence is: resampler only, then LoRA on the LLM, then the top ViT layers on in-domain Halo video.

### Context and when to act

Long visual history matters less than per-frame fidelity. NitroGen found **no benefit beyond one frame**, and Lumine's history ablation **peaked at 10 frames (2 s)**. A ~1-2 s high-rate window plus compressed memory is enough. StreamingVLM's recipe is the best tested: an attention sink, a 16-second vision window and a recent-text window, with contiguous RoPE. Removing contiguous RoPE dropped its win rate from **66.18 to 25.09**.

Eviction is mandatory. At 1,280 tokens/s, a Qwen3-VL-8B KV cache would fill 16 GB in ~90 s (est., 144 KiB per token).

The "when to respond" machinery from streaming chat maps onto "when to act". StreamMind's gate reuses the first four LLM layers and stays silent **310 times for every response** on Ego4D. Kevin can likewise prefill every frame and decode only at chunk boundaries or salient events ([StreamMind](https://arxiv.org/html/2503.06220v2)).

### The latency budget on the 3090 Ti

Two measured anchors: llama.cpp on a 3090 Ti processes a 7B Q4 prompt at **6,924 tokens/s** and decodes at **172 tokens/s** ([llama.cpp](https://github.com/ggml-org/llama.cpp/discussions/15013)). For comparison, Kevin's current Gemma vision call takes **0.74-0.91 s per frame** ([findings §6](../findings.md)), roughly Gemini Live's rate.

Scaled to 12B (est.), prefill is ~3,900 tokens/s. That makes 20 fps × 16 tokens (320 tokens/s) about 8% of capacity, and 20 fps × 256 tokens impossible. The binding cost becomes the vision encoder: an estimated **8-15 ms per frame at 224-256 px, 25-50 ms at 448 px**. Lumine's ViT alone took **39 ms per 720p frame** on 4×H20 ([Lumine](https://arxiv.org/html/2511.08892)).

High resolution, not frame rate, is what breaks a 20 fps budget.

## Async tool calls should carry one-second chunks, not keystrokes

Async tool calls are a good interface, but **the unit inside each call must be a chunk of actions, not a keystroke**.

### Why per-keystroke tokens fail

Robotics measured three failure modes. First, per-step action tokens at 20-50 Hz make policies "unable to make progress", because the cheapest way to lower the loss is to copy the last token ([FAST](https://arxiv.org/html/2501.09747)). Second, compressed autoregressive tokens fix training but decode at **~750 ms per chunk**. Third, a flow-matching action expert decodes a 50-step chunk in **27 ms on a 4090** ([π0](https://arxiv.org/html/2410.24164)). In Octo's ablation, the diffusion head scored **83% against 18%** for discretized actions ([Octo](https://arxiv.org/html/2405.12213)).

The 3090 Ti makes this sharper. Decoding a 12B model at ~100 tokens/s (est.) means a 20-token action chunk costs ~200 ms, an entire 5 Hz step. Chunks must therefore be either **≤5 event tokens** (key-down and key-up with frame offsets, a run-length code playing the role FAST plays for robots) or **decoded in parallel by a small head**. That head would be a ~100-300M flow or regression expert for mouse paths, reading the trunk's hidden states. GR00T reads 12th-layer embeddings this way ([GR00T N1](https://arxiv.org/html/2503.14734)).

### How execution stays asynchronous

Real-time chunking (RTC) makes asynchronous execution safe. The runtime **commits the first *d* actions of a chunk**, *d* being the inference delay, and a new call may only rewrite the uncommitted tail. Training with simulated delays of 0-10 steps costs only **8,000 extra steps** and tolerates **~200 ms at 50 Hz** ([training-time RTC](https://arxiv.org/html/2512.05964v2)). Going async without such care has a price: SmolVLA's async mode was 30% faster but lost a little success (**78.3% → 73.3%**) ([SmolVLA](https://arxiv.org/html/2506.01844)), a gap that RTC or VLASH's future-state conditioning closes ([VLASH](https://arxiv.org/html/2512.01031v1)). Kevin's numbers are easy by comparison: 100-150 ms of latency is only 2-3 frames at 20 fps (est.), well inside the 0-12 step ranges Physical Intelligence trains with.

Google's production stack shows what happens without this. The ER 2 Live API cancels in-flight tool calls whenever a new prompt arrives, and timer-driven heartbeats can cause a cancellation loop ([Gemini Robotics streaming](https://ai.google.dev/gemini-api/docs/robotics-streaming)).

Concretely, Kevin should emit two families of non-blocking calls. **Motor chunks** go out at ~5 Hz; each covers ~1 s of key events plus a mouse path and executes 30-50% before the next one replaces its tail. **Semantic calls** such as `say`, `set_goal` and `ask` go out at ≤1 Hz.

### Keeping the backbone listening and talking

Language preservation matters doubly if the same 12B must also be Kevin's voice. Physical Intelligence found that bolting a continuous expert onto a VLM "significantly harms both training speed and knowledge transfer". Its fix, **knowledge insulation**, has three parts: a stop-gradient from the expert, discrete action tokens on the backbone, and VQA co-training. It costs ~20% more per step. Without it, π0 needs **7.5× more steps** for similar performance ([KI](https://arxiv.org/html/2505.23705v1)). Other results point the same way. RT-2's co-fine-tuning lifted unseen tasks **52 → 63** at 55B ([RT-2](https://arxiv.org/html/2307.15818)). VLM2VLA kept **over 85%** of base VQA ability with LoRA and actions expressed as text ([ICLR 2026](https://iclr.cc/virtual/2026/poster/10007076)). SIMA 2, trained without such care, lost **25.5% (relative) on AIME and 16.3% on GPQA**.

For Kevin: keep the base frozen, put LoRA adapters on it, stop gradients from the mouse head, and devote 10-20% of tokens to VLM and text data.

### One model or two?

This dissolves most of the "one big model vs. dual system" debate. Every high-rate robot system passes a latent from a slow model to a fast one: Helix runs at 7-9 Hz to 200 Hz, GR00T at 10 Hz to 120 Hz ([Helix](https://www.figure.ai/news/helix)). A 12B trunk with a small action expert reading its mid-layer states *is* such a dual system, trained end to end, and Helix's own two halves were trained jointly.

What remains open is narrower. One question is whether the trunk also talks; the other is whether tactical, multi-step orders ("flank right, take cover, then attack") can be followed directly. **No published system shows the latter.** Gemini Robotics 1.5 keeps planning in a separate orchestrator that calls the VLA as a natural-language tool, and swapping a generic Gemini 2.5 Flash orchestrator for the embodied-reasoning one halved long-horizon failures (**44.5% → 22%**) ([GR 1.5](https://arxiv.org/html/2510.03342v3)). Kevin's existing actor, which decomposes orders into atomic skills, is the right place for that layer.

## A four-stage path costs about $10-35k and starts in OpenCE

### What to build first

Before any GPU spend, build a data plant on OpenCE. It needs **true-input logging** of keyboard and mouse at 20 Hz for Kevin's client, which the Open-P2P harness already half does by injecting and logging actions there. It needs an **engine event log** of weapon pickups, kills, region entries and vehicle seats. It needs **forkable save states**, so one state branches into several instructions with different outcomes; this is what makes language counterfactually necessary in the data. It needs **several parallel instances**, with a lockstep mode for RL. And it needs a **privileged teacher bot** that reads exact engine state and drives *player inputs*, not Halo's AI, through 15-20 atomic templates (go to, follow, attack target or nearest, pick up, switch weapon, take cover, hold, grenade, enter or exit vehicle, look at), switching instruction every 5-30 s and injecting noise so recovery states appear.

The teacher follows the Learning by Cheating recipe. There, a privileged driving agent trained on **~4 h of autopilot data** supervised a camera-only student to **100% on the original CARLA benchmark**, with DAgger relabelling for free ([LBC](https://arxiv.org/abs/1912.12294)). Kevin's skill library already names the templates. The work is re-expressing them as input-level controllers.

### Data budget

| Source | Hours | Labels | Cost (est. unless cited) |
|---|---|---|---|
| Halo teacher-bot rollouts | 50 (pilot) → 500-1,000 | true inputs; instruction issued before the action, 100% coverage; LLM paraphrases, 5-20 per template | game instances only |
| Counterfactual forks | 10-20% of bot hours | same state, ≥2 instructions | free |
| Halo human play (you, testers or contractors) | 50-100 | true inputs; instructions from engine events plus paraphrase | ~$1-2k at VPT's **$20/h** ([VPT](https://arxiv.org/abs/2206.11795)) |
| Open-P2P, FPS-like subset | ~1,000 of 8,300 | recorded keyboard/mouse; recaption Lumine-style | **$0.036-0.27 per video hour** on Gemini Flash-Lite to Flash ([pricing](https://ai.google.dev/gemini-api/docs/pricing)), ~$40-270 |
| D2E human play | 335 | recorded keyboard/mouse ([D2E](https://arxiv.org/abs/2510.05684)) | free |
| Halo grounding/VQA from engine state | 200-400k samples | exact (JARVIS-VLA's most valuable non-trajectory data) | free |
| General VLM/text mix | 10-20% of tokens | n/a | n/a |
| Optional think-aloud | ~15 h | human (Lumine's reasoning set) | ~$300 |

That puts ~2,000 h behind the action prior, crossing Lumine's ~1,800 h navigation threshold. It also gives 200-300 h of instruction-dense data, matching Lumine's 200 h, and it pools Halo with other FPS games, as Game-TARS's 42% → 65% result supports.

### Compute budget

The compute estimate scales Lumine's measured cost of **~3.1 H100-hours per gameplay hour per epoch** at ~6,000 visual tokens per second. At 200-750 tokens per second, Kevin's design uses 8-30× fewer tokens. Multiplying by 1.7 for a 12B over a 7B gives **~0.2-0.6 H100-hours per gameplay hour per epoch** (est.). Prices are $2.20-4.00 per H100-hour as of October 2026 ([joulemath](https://joulemath.com/blog/gpu-rental-prices-h100-h200-a100-rtx-4090-october-2026/)).

| Stage | Purpose and recipe | Data × epochs | H100-hours (est.) | Cost (est.) |
|---|---|---|---|---|
| 1. Pilot | Test whether language becomes counterfactually necessary. Qwen3-VL-8B LoRA, stock ViT at 224 px (~25 tokens/frame), 10 fps, event-token actions; ablate 4/16/64 tokens per frame | 60-70 h × 3 | 150-500 | $0.3-2k |
| 2. Video head + action pre-training | 12B; resampler to 16-32 tokens/frame at 20 fps plus a 1 Hz keyframe; progressive unfreezing | ~2,000 h × 2 | 800-2,400 | $1.8-9.6k |
| 3. Instruction + insulation | Flow mouse head with stop-gradient; instruction-dense data plus VQA co-training | ~250 h × 3 + VQA | 400-800 | $0.9-3.2k |
| 4. Closed loop | DAgger with the teacher, then GRPO/PPO on engine verifiers for weak templates; train with simulated delays | on-policy | 600-1,000 + game instances | $1.3-4k |
| Total | | | **~2,000-4,700** | **~$4.3-19k** |

Adding 1.5-2× for reruns and ablations, plus human play and captioning, gives the $10-35k all-in figure. Lumine's full history pipeline was ~20.7k H100-hours, or $46-83k at the same rates.

Stage 4 follows what works elsewhere. SimpleVLA-RL took LIBERO from **48.9% to 96.9%** after one-demo SFT with a binary reward. ROCKET-3 rose **7% → 28%** on 100,000 auto-generated Minecraft tasks, with rollouts on **3 nodes of two RTX 3090s each** ([SimpleVLA-RL](https://arxiv.org/html/2509.09674); [ROCKET-3](https://arxiv.org/abs/2507.23698)). Engine verifiers replace SIMA 2's Gemini judge for most templates. A VLM judge is needed only for fuzzy orders like "play aggressively".

Run a cheap control arm alongside: Open-P2P-600M fine-tuned on the same Halo data with text, plus Gemma as planner. My estimate is tens to ~150 H100-hours, scaled from Open-P2P's **1,120 H100-hours for 1.2B on 8.3k h** ([GitHub](https://github.com/elefant-ai/open-p2p)).

### What fits on the 3090 Ti

| Workload on b650s | Fits? | Basis |
|---|---|---|
| Dual system: Gemma 12B planner + Open-P2P-600M body + Breeze TTS | **Yes**: 21.3-21.8 GB, body at 19.6 Hz | measured ([local test](../reports/p2p-halo-zero-shot.md)) |
| Single 12B video-action model, 4-bit, 10 fps ingest, 5 Hz chunks | Compute yes (~40-50% GPU duty, est.). Memory ~10-12 GB vs Gemma's 8.9 GB, so it needs **2-3 GB freed from the 9 GB Breeze** | est. from config sizes; [findings §1](../findings.md) |
| Same at 20 fps | Marginal (~65% duty before TTS and game rendering) | est. |
| 12B in bf16 | No (~24 GB of weights) | est. |
| Training 8-12B, even LoRA | No: OpenVLA's 7B LoRA used **59.7 GB** | [OpenVLA](https://arxiv.org/html/2406.09246) |
| Data plant, evaluation, game instances | Yes; the game needs ~1.3 GB | local |

### Milestones that gate further spend

Each milestone is a go/no-go test before the next stage's spend.

**M1 is the pilot's test.** Engine-verified success must clearly beat instruction-removed, instruction-swapped and junk-token controls on held-out maps and paraphrases. If swapping the instruction does not change behaviour, add counterfactual forks before scaling. The pilot also produces the first published-style curve of action accuracy against tokens per frame for a VLM.

**M2: the 12B serves at 10 fps on b650s.** Capture to committed action must stay within ~150 ms (est.).

**M3: the single model beats the dual-system control arm** on the same evaluations. If it does not, ship the dual system, where Gemma's voice already lives.

Generality across environments needs a second held-out environment. ViZDoom runs at up to **130,000 frames per second** on one node, so the simulator is never the bottleneck there; the policy is ([Sample Factory](https://arxiv.org/abs/2006.11751)).

## Where the new evidence corrects the earlier survey

Nine claims in the earlier survey need correcting or qualifying:

| Earlier claim | What the new notes show | Consequence |
|---|---|---|
| Lumine's 2B "stopped improving after ~1,200 h" | Its **loss kept falling but benchmark performance degraded** past ~1,200 h; 7B improved on both ([Lumine](https://arxiv.org/html/2511.08892)) | A stronger case for ≥7B trunks |
| Lumine: "half the errors were visual misunderstanding" | "Perceptual misrepresentation" is the *most frequent* error type; **no percentage is given** | Drop "half" |
| Lumine's zero-shot transfer was demos without numbers | Wuthering Waves **107 vs 101 min** for new players; Honkai: Star Rail **7 h vs 4.7 h** | Transfer within a genre is quantifiably near human |
| Open-P2P "pick up shotgun: 5/5 with text vs 1/5 without" | Not found in the paper, project page or README. The published test is Quake red buttons, **~20% → ~80%** ([project](https://elefant-ai.github.io/open-p2p)) | Treat 5/5 as unverified |
| FDM-1: no language transfer "so no text instructions"; weights not released | Trained without language-model initialisation but with **1.25T transcript tokens for downstream instruction tuning**; no instruction interface published. Weight release is **unconfirmed either way**: aggregators claim a release, primary sources don't say ([si.inc](https://si.inc/posts/fdm1/); [SiliconANGLE](https://siliconangle.com/?p=744245)) | An action prior with a latent language path, not a language-free model |
| Game-TARS: proprietary Seed-VL-1.5, 500B tokens | **526B tokens**; MoE-mini is 2.5B active; a Dense variant uses open **Qwen2.5-VL-7B**; other games' data lifts Minecraft **42% → 65%** ([Game-TARS](https://arxiv.org/html/2510.23691)) | The recipe works on an open backbone, and cross-game pooling pays |
| "RL from in-game reward is rare; imitation dominates" | True for small pixel policies. VLM agents now add RL after SFT routinely: UI-TARS-2 **44.3 → 59.8**, ROCKET-3 **7% → 28%**, SIMA 2 self-improvement | RL belongs in the plan as Stage 4 |
| Real-Time EXPO-FT "42% → 97% with ~10 minutes" | Could not be located. The nearest verified result is ConRFT, **96.3% after 45-90 min** online ([ConRFT](https://arxiv.org/abs/2502.05450)) | Unverified |
| "Keyboard/mouse labels can't be read from ordinary videos" | IDMs read them: VPT **90.6%** keypress accuracy from a 100-2,000 h seed; D2E 47-77% on FPS keyboards; FDM-1 labelled 11M h. Out-of-domain labels help coarse skills only | Possible but unnecessary for Kevin; log true inputs |

## Conclusion

Ranked by how hard they are for Kevin rather than for the field, the missing ingredients look different from the literature's ordering. **Causal, counterfactual instruction data**, the field's bottleneck, is Kevin's easiest win: Lumine needed 70 annotators and a classifier pipeline, while OpenCE's teacher bot and forkable states produce better-ordered labels at no labelling cost. **A video head of 16-32 tokens per frame, trained on actions**, is the one ingredient with a real unknown, because no published curve shows whether that budget keeps the detail needed to aim at a distant Elite; the pilot answers it for ~$1-2k. **Chunked async tool calls with a fast action head, training that keeps the backbone listening and talking, and closed-loop DAgger plus RL** each have working robotics templates that need porting, not inventing. **Throughput** is mostly a consequence of the token budget, and that budget is why the whole path costs ~$10-35k when Lumine's compute alone would cost $46-83k today, despite running at 2-4× the frame rate.

Two problems sit beyond the plan, and nobody has solved either. One is following tactical multi-step orders directly; the other is new games' specific mechanics, which pre-training improves by only ~5%. Both argue for keeping a planner that breaks orders into atomic steps, and for small per-game data top-ups, rather than expecting one model to follow any order in any game.

The larger shift is in where the money goes. In Lumine's world, human labelling and 720p tokens dominate the cost. In Kevin's, labels are free and tokens are cheap, so the budget moves to the engineering of the data plant and the evaluation harness. That work runs on the hardware Kevin already has.
