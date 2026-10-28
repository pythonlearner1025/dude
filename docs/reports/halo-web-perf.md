# OpenCE m8 web frame-pacing report

## Result

On b650s, the m8 web build is within 0.1% of the current upstream web release in every final
60-second scenario, including a deliberately excessive active-m8 workload. There is no sustained
m8 regression to fix on this machine. The active mock alternated `look` and `go_to` about every
four seconds and streamed 24 kHz mock TTS; this is about 16 times the user's observed view cadence
(8 views in five minutes).

The one m8-specific cost that is visible is a synchronous companion view read-back. Most captures
took 1--7 ms on the RTX 3090 Ti, but the worst measured `glReadPixels` took 22 ms and produced one
roughly 40 ms frame. That can explain an occasional hitch exactly when Kevin looks, but not
continuous bad pacing at the user's real 0.027 views/second. State generation is already sent at
2 Hz (`COMPANION_STATE_TICKS = TICKS_PER_SECOND / 2`), not every rendered frame. Continuous mock
audio, state messages, page-thread WebSocket proxying, and frequent view sends did not lower the
60-second frame rate.

The shipped change is therefore diagnostic and off by default: `?perf=1` logs worker-side FPS,
p50/p95/p99 frame time, longest frame, and each companion view's read-back/total time. A speculative
PBO/fence implementation was tested and discarded: WebGL/ANGLE did not make later pack-buffer
fences readable promptly, and forced collection caused 300+ ms stalls. The synchronous production
path remains unchanged.

Commit: `76db971748bbe7adcd1478c54ea52cd696643a5c`

## Test environment and isolation

- Google Chrome 153.0.8010.52, visible 1280x720 window on the existing `DISPLAY=:1` Xorg display.
- CDP `SystemInfo.getInfo`: `ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 3090 Ti/PCIe/SSE2,
  OpenGL 4.5.0 NVIDIA 580.95.05)`, `gl=egl-angle,angle=opengl`. SwiftShader was not enabled.
- One Chrome instance at a time. No Xorg or Sunshine process was stopped or changed.
- Upstream baseline: GitHub release `build-309`, commit
  `22947203a52c6f4b04171eaec426b4f5059b43f4`, asset `halo-web-release.zip`, SHA-256
  `7a945eda71b6a00c882608f0aa2d47eb0aa361b083cffd90c4c582af64720b02`.
- All pages were served at `http://127.0.0.1:18000` with the same persistent browser origin and
  the user's maps copied only into local OPFS.
- The isolated mock used 18080/18081/17860/18083, site 18090, WebSocket mic/game 18091, and TCP
  game 18092. The real m8py stayed on PID 2176732 and ports 47800/8090/8091 throughout. The real
  model ports 8080/8081/7860/8083 were not contacted, restarted, or changed.

## Measurement method

The Playwright harness is `/home/minjune/m8work/codex-out/halo-web-perf.mjs`. It samples the game's
shared presented-frame counter on browser animation frames, clears only HTTP/service-worker caches
between builds (not OPFS), and uses raw CDP `Tracing.start`/`Tracing.end`. Each row is a 60-second
sample after a warm-up. For gameplay rows the harness sent Space/Escape to skip the opening and
waited 15 seconds for a10 or 20 seconds for b30. The table reports mean FPS, then p50/p95/p99 and
maximum observed inter-frame time in milliseconds.

The harness timestamps are quantized to browser animation frames. A counter jump retains the right
FPS count but cannot reconstruct the individual skipped timestamps. The opt-in worker log is the
more precise instrument for a Mac follow-up. b30's unscripted fight also varies substantially with
the exact AI/cutscene phase: the first pass ranged from 50.6 to 59.8 FPS, while every repeat was
59.7--59.8 FPS. This is run-to-run scene variance, not a code change (upstream is immutable).

## Before and after matrix

| Build/link | Phase | Before: FPS / p50 / p95 / p99 / max ms | After: FPS / p50 / p95 / p99 / max ms |
| --- | --- | ---: | ---: |
| Upstream build-309 | a10 opening cinematic | 59.75 / 16.67 / 16.67 / 16.67 / 183.32 | 59.92 / 16.67 / 16.67 / 16.67 / 66.66 |
| Upstream build-309 | a10 first gameplay | 59.99 / 16.67 / 16.67 / 16.67 / 16.67 | 59.98 / 16.67 / 16.67 / 16.67 / 16.67 |
| Upstream build-309 | b30 beach gameplay | 50.57 / 16.67 / 33.33 / 50.00 / 183.33 | 59.75 / 16.67 / 16.67 / 16.67 / 183.33 |
| m8, disconnected port 9 | a10 opening cinematic | 58.39 / 16.67 / 16.67 / 33.33 / 233.32 | 59.94 / 16.67 / 16.67 / 16.67 / 33.34 |
| m8, disconnected port 9 | a10 first gameplay | 58.71 / 16.67 / 16.67 / 33.33 / 50.00 | 59.98 / 16.67 / 16.67 / 16.67 / 33.33 |
| m8, disconnected port 9 | b30 beach gameplay | 52.58 / 16.67 / 33.33 / 33.34 / 266.65 | 59.78 / 16.67 / 16.67 / 16.67 / 183.32 |
| m8, active isolated mock | a10 opening cinematic | 59.95 / 16.67 / 16.67 / 16.67 / 50.00 | 59.93 / 16.67 / 16.67 / 16.67 / 50.00 |
| m8, active isolated mock | a10 first gameplay | 59.98 / 16.67 / 16.67 / 16.67 / 16.67 | 59.93 / 16.67 / 16.67 / 16.67 / 66.67 |
| m8, active isolated mock | b30 beach gameplay | 59.80 / 16.67 / 16.67 / 16.67 / 150.00 | 59.71 / 16.67 / 16.67 / 16.67 / 183.33 |

Final active-mock differences from the simultaneous upstream repeats are 0.02% (a10 cinematic),
-0.08% (a10 gameplay), and -0.07% (b30). Disconnected differences are +0.03%, 0.00%, and +0.05%.

The unusually large maxima are isolated transitions or missed page samples; p99 remains one 60 Hz
frame in all final rows. The worker log during active a10 recorded 26 view captures: most read-backs
were 1--7 ms, with three late captures at 18, 21, and 22 ms. Active b30 recorded nine captures,
three at 21--22 ms. Those events line up with the occasional worker-log longest frames around
39--49 ms.

## Trace evidence

Representative traces:

- Final active m8 a10 gameplay:
  `/home/minjune/m8work/run/halo-perf/after-ours-mock-a10-gameplay-trace.json`
  (102 MiB, SHA-256 `dd3868ae8827d65cbffae292891643b0695ac24021141548e8c084d8757b1dd1`).
- Upstream a10 cinematic:
  `/home/minjune/m8work/run/halo-perf/before-upstream-a10-cinematic-trace.json`
  (64 MiB, SHA-256 `28cdaa3095072be703fe84a3f7a170c57d50e8a15a91f633066fa2c0e03927e6`).

In the active trace's 10-second window, the dedicated game worker contains five
`GLES2::ReadPixels` slices at 1.014, 1.322, 1.447, 1.530, and 2.091 ms. The longest non-profiler
game-worker task was 15.9 ms. No m8 WebSocket/proxy task above 5 ms appears on `CrRendererMain`;
the only nested 33 ms main-thread group is CDP's own `CpuProfiler::StartProfiling`. GPU work is on
`CrGpuMain`, while the game loop and `ReadPixels` are on the `DedicatedWorker thread`. This rejects
the hypothesis that ordinary page-thread proxying continuously blocks the game worker on b650s.

The longer read-back spikes happened outside that 10-second trace but are recorded by the new
worker telemetry, for example:

```text
halo-perf: companion view 636x286, read-back 22.00 ms, total 23.00 ms
halo-perf: 60.04 fps, frame ms p50 16.65 p95 17.57 p99 17.83, longest 39.55
```

## Root-cause assessment

1. **No sustained m8 gap is reproducible on b650s.** Continuous PCM, 2 Hz state frames, async
   page-thread sends, and very frequent view requests leave mean FPS and p99 at upstream levels.
   Consequently there is no evidence for throttling state further, coalescing audio, or replacing
   the WebSocket bridge.
2. **Companion views can cause isolated synchronous GPU stalls.** `write_companion_view` calls
   `glReadPixels` before present. This is measurable, but at the user's eight views per five minutes
   it cannot explain continuous poor motion. A WebGL PBO experiment made this worse and was not
   shipped.
3. **The remaining report is machine/browser-specific frame pacing or baseline WebGL behavior.**
   Low CPU/GPU utilization is consistent with a scheduling/vsync stall rather than saturation.
   The baseline itself showed substantial b30 run variance, and this Linux/NVIDIA host cannot
   reproduce the Mac/ANGLE-on-Metal condition directly. The new `?perf=1` output is intended to
   distinguish a steady 60/30 Hz cadence from Mac-only long frames and to correlate any hitch with
   companion views.

## Changed files

- `port/web/src/web_main.c`: opt-in game-worker frame intervals and two-second FPS/percentile log.
- `port/linux/src/d3d8_gl.c`: web-only timing around the existing companion `glReadPixels` and send.
- `port/web/site/app.js`: maps `?perf=1` to `HALO_PERF_LOG=1`.
- `port/web/README.md`: documents the address parameter.

Normal play has no added clock reads, sorting, or logging because the environment flag is checked
once and the fast path returns. The companion protocol and all native behavior are unchanged.

## Recommended Mac URLs

Start with diagnostics while preserving the current picture:

```text
http://localhost:8000/?m8=ws://100.126.232.8:8091/game&perf=1
```

If pacing remains poor, force the stock 640x480 render and ensure expensive saved anti-aliasing is
off. This is the highest-value Retina test even though the reported 1008x574 drawable is not large:

```text
http://localhost:8000/?m8=ws://100.126.232.8:8091/game&perf=1&set=HALO_RESOLUTION_SCALING=original&set=HALO_ANTI_ALIASING=off
```

If the user prefers a steady original-rate presentation to uneven 60 Hz interpolation, add:

```text
&set=HALO_INTERPOLATION=false
```

That last setting intentionally presents the original 30 FPS, so it is a pacing fallback rather
than a 60 FPS optimization. `HALO_NO_VSYNC=1` is not recommended first: the web main loop is still
driven by the browser's worker animation frames, so it does not bypass Chrome's compositor pacing.

## Build, package, and deploy

Final validation:

```text
node --test "port/web/tests/*.test.js"       14 passed
uv run --with pytest pytest -q tools/test_web_build.py   10 passed
ninja web                                    passed
ninja linux                                  passed
```

Artifacts:

- `/home/minjune/m8work/web-dist/halo-m8-web/`
- `/home/minjune/m8work/web-dist/halo-m8-web.tgz`
- tarball SHA-256: `a13d620e9222a0771c6874480944a0d78acccaf2b4debb0f01906eb8c4cec97a`
- `/home/minjune/m8work/codex-out/opence-m8-web.patch` (binary-safe diff from `m8-linux`)

The packaged `version.json` is stamped with commit `76db9717`. Neither package contains a `maps/`
directory or any `.map` file.

On the Mac, stop only the currently running packaged server with Ctrl-C, extract over the existing
folder (the archive has no maps, so `~/halo-m8-web/maps/` remains), and restart:

```sh
cd ~
tar -xzf ~/Downloads/halo-m8-web.tgz
cd ~/halo-m8-web
python3 web_serve.py
```

Then open one of the URLs above. In Chrome DevTools Console, filter for `halo-perf:` and capture at
least 30 seconds covering the a10 cutscene and gameplay. If long-frame lines coincide with
`companion view`, the Mac's Metal read-back is the culprit; if they do not, the data identifies the
base web frame-pacing problem without involving m8py.
