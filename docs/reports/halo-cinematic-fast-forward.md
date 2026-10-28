# K: fast-forward unskippable cinematics

## Result

OpenCE now runs solo cinematics at an effective 8x engine game-time rate whenever the
existing checkpoint-revert skip cannot safely apply. The feature is default-on, preserves
the map script's exact `game_speed`, heavily ducks the game's mixer, and suppresses
fast-forwarded cinematic dialogue on the m8 companion's kind-3 hear stream. It stops as
soon as the native skip becomes safe or the cinematic ends.

The change is committed on `m8-web`, both requested builds and web test suites pass, the
map-free Mac package is ready, and the binary branch patch is exported.

## Mechanism

- `source/cutscene/cinematics.c`: `cinematic_fast_forwarding()` is true only when:
  - `cinematic_in_progress()` is true;
  - the game is a local/solo game;
  - `game.fast_forward_cinematics` is enabled; and
  - the existing automatic skip is not presently safe and ready (skippable region,
    `game.skip_cinematics`, valid completed checkpoint, and no map save in progress).
- `source/game/game_time.c`: `game_time_effective_speed()` multiplies the engine's existing
  `game_time_globals->speed` by 8 for the tick rate, frame time, and interpolation fraction.
  It does not write the underlying scalar. A script's speed therefore remains intact and is
  restored exactly and immediately when fast-forward ends. The normal engine cap of 100 is
  retained.
- The existing `cinematic_render()` checkpoint-revert skip remains preferred. Once its
  checkpoint is valid, fast-forward stops and `main_skip_cinematic()` follows the unchanged
  `game_state_revert()` path. No scenario scripts, checkpoints, objectives, or map data are
  rewritten.
- Fast-forward is solo-only so it cannot desynchronise distributed co-op machines.

## Setting

| Config | Environment / web query | Default |
| --- | --- | --- |
| `game.fast_forward_cinematics` | `HALO_FAST_FORWARD_CINEMATICS` | `true` / `1` |

`?set=HALO_FAST_FORWARD_CINEMATICS=0` disables only fast-forward. The existing
`game.skip_cinematics` / `HALO_SKIP_CINEMATICS` native skip remains independent.

The setting is declared in `port/linux/src/port_config.c` and documented in
`port/linux/README.md`.

## Audio and companion handling

- `source/sound/sound_manager.c`: `sound_manager_master_gain()` applies a 0.02 multiplier
  during fast-forward. This ducks all game classes, including already-playing dialogue,
  without stopping or altering the map's sound state.
- `port/linux/game/companion.c`: `companion_note_sound()` drops scripted-dialogue kind-3
  hear frames only while `cinematic_fast_forwarding()` is true. The wire protocol is
  unchanged.
- In the controlled `b30` comparison, fast-forward enabled forwarded 0 opening kind-3
  frames; disabled forwarded 4. After control, the Sergeant's radio line was forwarded
  normally.
- In a focused `a30` post-control run, regular Kevin state frames resumed and two Cortana
  radio lines were forwarded normally (speakers reported as `Cortana`, `react:true`).

## Headless verification

Chrome used a fresh persistent profile, headless Playwright, SwiftShader
(`--use-angle=swiftshader --enable-unsafe-swiftshader`), fake media, local port 8010, and
the requested `build/linux/maps` symlink. The game link and microphone both pointed at the
isolated mock `ws://127.0.0.1:18192`; the live m8py, model services, Mac, Xorg, and Sunshine
were not contacted or changed.

The control boundary was the first post-cinematic companion `state` frame, as in the prior
level report. Each run then held Forward for 1.2 seconds, waited, captured a screenshot,
and checked subsequent state/event/hear traffic.

| Level | Fast-forward on | Fast-forward off | Overall wall-clock improvement |
| --- | ---: | ---: | ---: |
| `b30` | **30.590 s** | 96.074 s | 3.14x |
| `a30` | **7.242 s** | 5.675 s | native skip in both; timing noise |
| `a50` | **22.334 s** | 80.742 s | 3.62x |
| `c10` | **28.898 s** | 97.825 s | 3.39x |

SwiftShader could not sustain the configured 8x simulation rate: the observed whole-run
factor was about 3.1x to 3.6x on the unskippable levels, including load/fixed overhead.
This is a rendering/simulation throughput cap, not a lower configured multiplier. At a
sustained 8x rate, `b30`'s approximately 90-second opening is expected to consume roughly
11-12 seconds plus load time, which is consistent with the under-20-second real-hardware
target; the user's Mac was explicitly out of scope and was not tested.

Post-control checks:

- `b30`: normal first-person beach gameplay, checkpoint completion, repeated Kevin state
  messages, `{player} got out of the pelican.`, and the Sergeant radio dialogue.
- `a30`: normal first-person crash-site gameplay, repeated Kevin state messages, and two
  Cortana radio dialogue frames after control.
- `a50`: normal first-person gameplay and repeated Kevin state messages.
- `c10`: normal first-person gameplay, repeated Kevin state messages, and
  `New objective: >> Locate Captain Keyes.`

Screenshots are `/home/minjune/m8work/logs/ff-<level>-on.png` and
`ff-<level>-off.png` for all four levels, plus `ff-a30-post-control.png` and
`ff-b30-post-control.png`. Raw timing results are in
`/home/minjune/m8work/logs/ff-results.json`.

## Side effects found

No gameplay-state, checkpoint, objective, or post-control companion regression was found.
The only observed limitation was SwiftShader's CPU/render cap. `a30` remains governed by
the native checkpoint-revert skip, so its 1.567-second enabled/disabled difference is run
variance rather than a fast-forward effect.

## Builds and tests

- `ninja web`: passed.
- `ninja linux`: passed.
- `node --test "port/web/tests/*.test.js"`: 14/14 passed.
- `python -m pytest -q tools/test_web_build.py`: 10/10 passed (dude Python 3.12 venv).
- `git diff --check`: passed before commit.

## Commit and artifacts

- Commit: `b6f243022d4619e163677f203673752c30834cd9`
  (`Fast-forward unskippable cinematics`)
- Package directory: `/home/minjune/m8work/web-dist/halo-m8-web/`
- Package: `/home/minjune/m8work/web-dist/halo-m8-web.tgz`
- Package SHA-256: `33db5664406153247646d7bb429a75538a7bcee83d27e6f59fbec3dc6f9e58a7`
- Package size: 10,948,754 bytes
- Existing `README-MAC.md` preserved SHA-256:
  `ba060651f9ec0ecef7696a1811b1ae31bc06fa0ca2f9b4331bd28e474188247d`
- Package check: no `maps` path and no `.map` file.
- Binary patch (`m8-linux` to `m8-web`):
  `/home/minjune/m8work/codex-out/opence-m8-web.patch`
- Patch SHA-256: `0e622f00d91eb8f107f52ebca39d5fd3070b64369edd8ada5d6521e4e1c1f7d2`
