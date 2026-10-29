# Open-P2P Halo CE zero-shot test

Tested 2026-10-28 on b650s (Ubuntu 22.04, RTX 3090 Ti 23 GB, NVIDIA 580.95.05) with OpenCE a30 co-op on X display `:1`.

## Setup

The existing Python 3.13 environment used CPU-only PyTorch 2.15.0. I replaced it with the repository lock's CUDA 12.8 pair, `torch 2.9.1+cu128` and `torchvision 0.24.1+cu128`, and installed the small client dependencies `evdev 2.0.0`, `mss 10.2.0`, and `python-xlib 0.33`. `torch.cuda.is_available()` is true and identifies the RTX 3090 Ti. Installation used `UV_NO_CACHE=1`; the uv cache remained 11 MB. The immediate filesystem delta was 6,121,037,824 bytes (5.70 GiB). Including compilation caches, recordings, and logs, the final task delta was 6,532,603,904 bytes (6.08 GiB), below the 8 GB cap.

Only Kev was stopped. `run/kev.pid` unexpectedly contained one live PID and one stale token; the live process command line was verified as the Kev-4B llama-server before sending SIGTERM. The other GPU servers were not changed.

The stock 1200M checkpoint could not fit beside the remaining m8 stack: it OOMed while its inference module approached the roughly 4.1 GiB available after Kev stopped. Loading checkpoints through CPU first removed training-checkpoint peak VRAM, but the 1200M module itself still did not fit. The requested fallback, 600M, fit.

The 600M policy and text encoder initially ran at 12.2 Hz eager. Open-P2P recomputed the unchanged 300M instruction embedding every frame. Caching that embedding by instruction and keeping its encoder on CPU raised eager throughput to 15.8 Hz and freed compilation headroom. Compiled steady-state inference measured 9.71 ms/step (103 Hz) in the built-in benchmark; live end-to-end operation was capture-limited to about 19.6 Hz.

The Linux client is `dude/tools/p2p/client.py`. It:

- locates the Kevin X11 client window by `_NET_WM_PID` (title is an optional fallback);
- uses mss's `MSSImplXShmGetImage` MIT-SHM backend with cursor compositing;
- Hamming-resizes the complete client area directly to 192x192 RGB24 with no crop, padding, or aspect preservation;
- uses independent send/receive tasks over the raw little-endian length-prefixed protobuf socket and tolerates dropped IDs;
- creates one combined uinput keyboard/mouse, converts held snapshots to edges, scales relative mouse deltas, and releases all held input on focus loss or exit;
- checks X focus before every action. The episode harness also re-focuses the exact Kevin PID while it holds `display1.lock`, because Openbox occasionally moved focus away during long unattended takes;
- logs capture, send, inference, injection, and capture-to-injection timing plus every returned action to JSONL.

`server.py` launches Open-P2P with `--input_text` and polls `run/p2p-instruction.txt` at 10 Hz, writing changed nonempty instructions to the server's stdin. Upstream ignores an empty stdin line, so returning from a nonempty instruction to empty requires restarting the server; an initially empty instruction works. The three takes were ordered empty, move, shoot, so no reset was needed.

Run the server and client together after Kevin's game exists:

```bash
cd /home/minjune/m8work/open-p2p
source env.sh
/home/minjune/m8work/dude/tools/p2p/run.sh --model 600M
```

Or launch `server.py --model 600M` and `client.py --window-pid-file /home/minjune/m8work/run/kevin-client.pid` separately. Change the instruction atomically by replacing `/home/minjune/m8work/run/p2p-instruction.txt`.

## Mouse calibration

OpenCE's native input code applies 0.0022 radians/count at Halo mouse sensitivity 1. I set `HALO_MOUSE_SENSITIVITY=0.61091`, whose nominal value is 0.077 degrees/count. A 100-count uinput test measured only 6 degrees in the integer-degree network log, so the final client multiplier is 1.28. Validation injected 128 uinput counts for 100 model counts and changed Kevin's logged aim yaw from 95 to 87 degrees: about 0.080 degrees/model-count, within the log's one-degree precision of the 0.077 target. Larger one-shot tests were rejected because X11/SDL clamps them near 49 degrees and they are not a linear calibration.

Halo uses the model vocabulary's `Space`, `1`, `a`, `d`, `e`, `f`, `q`, `w`, `s`, and `z` under its defaults. It does not use literal `2`, `3`, `4`, the four arrow keys, or either Shift key for gameplay (default crouch is Left Ctrl/C). They are still mapped literally as required, but have no normal gameplay effect.

## Episode results

Each take was a fresh a30 host/client session, exactly 60.0 seconds at 15-fps H.264 recording. “Stuck” is the number of one-second network-state intervals with less than 0.10 m displacement. Distance is accumulated 3D path length; the parenthesized value is start-to-end displacement. Latency includes the first instruction embedding outlier; p95 reflects normal steady state.

| Instruction | Loop rate | End-to-end mean / p95 | Inference median / p95 | Total GPU VRAM mean / max | Distance (net) | Stuck | K / D |
|---|---:|---:|---:|---:|---:|---:|---:|
| empty | 19.63 Hz | 20.35 / 20.19 ms | 12.65 / 13.00 ms | 21,828 / 21,830 MiB | 22.70 m (5.41 m) | 26 s | 0 / 0 |
| `move forward` | 19.58 Hz | 22.18 / 21.96 ms | 14.61 / 15.50 ms | 21,832 / 21,833 MiB | 0.10 m (0.10 m) | 60 s | 0 / 0 |
| `shoot the enemies` | 19.60 Hz | 25.04 / 25.70 ms | 13.99 / 14.73 ms | 21,842 / 21,843 MiB | 0.34 m (0.31 m) | 59 s | 0 / 0 |

Mean latency is slightly above p95 because each nonempty instruction update caused one CPU text-embedding outlier of about 1.2 seconds. Capture averaged 6.22, 6.04, and 9.04 ms respectively; send was below 0.1 ms and injection below 1 ms. The m8-minus-Kev baseline was 18,207 MiB total GPU use; Open-P2P added about 3,238 MiB before games, while the full episodes peaked at 21,843 MiB total.

Raw and summarized artifacts are in `/home/minjune/m8work/p2p-test/`: the three MP4 files, `*-actions.jsonl`, `*-gpu.csv`, `*-client.log`, `*-host.log`, `metrics.json`, calibration text, three PNGs per episode, and `keyframes-contact-sheet.png`.

## Qualitative observations

- Empty: Kevin did walk and turn. The first keyframe looks down at grass after picking up ammo/grenades; later keyframes face out into the valley with a pistol. The 22.7 m path confirms real wandering, but it was not purposeful and no enemy engagement occurred.
- Move forward: all three keyframes remain just inside the lifepod doorway, looking at the same dead Marines and items. The model emitted literal arrow keys much more often than `w`; Halo does not bind those arrows for movement. The instruction was not followed in this take.
- Shoot the enemies: Kevin stayed at the doorway and fired repeatedly (the assault-rifle counter falls from about 40 to 21 across the keyframes), while looking down at corpses/items. No kills were recorded and no live enemy is visibly tracked. This is shooting behavior, but not convincing enemy identification or successful combat.

## Problems and limits

- 1200M cannot coexist with the fixed m8 GPU residents on this 23 GB card; 600M was required.
- The first embedding after each changed instruction is a roughly 1.2-second latency spike. It does not affect steady-state rate but is visible in the mean/max.
- Openbox occasionally removed focus. The client always ceased input when that happened; a PID-specific focus watchdog under the display lock restored it. Final takes still contain brief focus gaps (33-61 actions of roughly 1,175), but no input was injected during them.
- Zero-shot instruction following was poor: the prompted movement take did not move, and the prompted shooting take fired without finding/killing an enemy. The success here is the real-time Linux transport/control path, not competent Halo behavior.
- Empty instructions cannot replace a previous nonempty instruction through upstream stdin because empty lines are ignored.
- `/dev/uinput` had a contradictory ACL (`input` group entry `---`) despite its mode bits. A narrow `user:minjune:rw` ACL was added to the single device.
