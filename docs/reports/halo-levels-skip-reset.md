# J2 campaign-level launcher, cinematic skip, and fresh Kevin

## Result

The requested changes are committed in both repositories. The web launcher has all ten campaign
levels, a click reloads directly into the chosen level, fresh `map_name` starts no longer restore
the game's persistent campaign save, and the game sends m8py a reliable `new_game` transition.
m8py then starts the level with an empty feed and summary and no checkpoint snapshots from any
earlier level or session.

Automatic cinematic skipping is default-on and setting-gated. It successfully reduced `a30` from
133.507 seconds to player control to 5.595 seconds in the controlled headless run. The stock map
scripts do not expose all cinematic time as skippable: most of `b30`'s long opening remained and
measured 87.364 seconds enabled versus 89.678 seconds disabled. This is an engine/script limitation
under the requested “existing skip path only; no script rewriting” constraint.

## Cinematic skip mechanism and change

The stock input path is:

1. Space maps to the player's accept/jump input.
2. `player_control_action_test_check_reset_input_blob` checks
   `cinematic_can_be_skipped()` and calls `main_skip_cinematic()`.
3. At the end of the frame, `main_skip_cinematic_private()` restores the checkpoint with
   `game_state_revert()`. The scenario script observes the revert and continues after the
   cinematic. Network co-op uses the same revert after its vote path.

`source/cutscene/cinematics.c` now requests that exact deferred path when all of these are true:

- the level script has entered `cinematic_skip_start` / `cinematic_skip_stop`'s skippable region;
- `game.skip_cinematics` is enabled;
- the checkpoint exists and is no longer being written; and
- this skippable region has not already requested its automatic skip.

Waiting for the completed checkpoint is important: requesting the native revert on the first
`cinematic_skip_start` frame can precede the script's asynchronous checkpoint and restart the map.
The request latch is outside reverted game state, so one automatic request cannot restore itself
and loop.

Setting:

| Config | Environment / web query | Default |
| --- | --- | --- |
| `game.skip_cinematics` | `HALO_SKIP_CINEMATICS` | `true` / `1` |

`?set=HALO_SKIP_CINEMATICS=0` restores normal Space-to-skip play. The setting is documented in
`port/linux/README.md` and generated into `config.toml` by the normal settings system.

### Cinematics this cannot skip

This deliberately cannot skip time for which the map script has not enabled
`cinematic_can_be_skipped`: loading, title-only/scripted-camera sequences outside a
`cinematic_skip_start`/`stop` region, and any other map-authored unskippable section. Bink movies
are not played by these ports in the first place.

The tested campaign exception is `b30` (The Silent Cartographer): its long Pelican/beach opening
has no materially useful stock skippable window. The enabled/disabled timings differed by only
2.314 seconds and both runs showed the opening before control. `a30` is a positive control: its
opening did expose the normal skip region and automatic skip saved 127.912 seconds. No scenario
scripts or map data were rewritten.

## Level grid and fresh map starts

The launcher's new responsive two-column grid (one column on a narrow screen) lists:

- `a10` Pillar of Autumn
- `a30` Halo
- `a50` Truth and Reconciliation
- `b30` The Silent Cartographer
- `b40` Assault on the Control Room
- `c10` 343 Guilty Spark
- `c20` The Library
- `c40` Two Betrayals
- `d20` Keyes
- `d40` The Maw

Buttons remain disabled until browser checks and game-data import finish. A click preserves the
existing companion/settings query parameters, sets `map=<level>&play`, and navigates, so it also
reloads correctly if invoked after the Wasm game has started. `?map=` writes the existing
`map_name levels\\<level>\\<level>` init command.

The HS/console `map_name` evaluator now calls a fresh-map wrapper that disables persistent-storage
restore for that map start. The campaign menu's direct C calls are unchanged: Continue and Load
Game can still restore the selected save, and checkpoint `saved`/`loaded` behavior within a run is
unchanged.

The microphone permission was already granted in the fresh browser profile; it auto-started and
showed `Connected` on the launcher while the level grid remained usable.

## `new_game` protocol

### Game side

On a fresh campaign `main_new_map` (persistent restore disabled), the game queues:

```json
{"type":"new_game","level":"a30"}
```

The level is restricted to one of the campaign levels. `companion.c` retains this transition until
the m8 link is connected, preventing a startup race from dropping it. It then sends it through the
same kind-1 JSON path as `saved` and `loaded`. Save loads and checkpoint reverts do not emit
`new_game`.

### m8py side

`GameLink` routes `new_game` to the brain and clears its stale old-level state during loading.
`Brain.on_new_game`:

- clears the memory feed and summary;
- clears in-memory checkpoint `saves` and writes `[]` to `saves.json`;
- increments `memory_generation`, so an in-flight old summary is rejected;
- resets the summarizing flag;
- interrupts the current speech generation and sends `stop_audio`; and
- traces exactly `(new game: <level>, memory reset)`.

`docs/m8-architecture.md` documents the new backward-compatible JSON message. Tests cover state
routing, all memory/snapshot clearing, stale-summary rejection, speech interruption, `stop_audio`,
and the trace text.

## Verification

### Builds and automated tests

Configured in `/home/minjune/m8work/halo-skip` with:

```sh
python3 configure.py --release --portable --linux-cc clang-22 \
  --web-emcc /home/minjune/emsdk/upstream/emscripten/emcc
```

The portable sysroot and SDL3 input were copied from the main tree before configuration; the main
source working tree and its branches were not used for changes.

- `ninja web`: passed (727-step clean build; subsequent final incremental link passed).
- `ninja linux`: passed (835-step clean build; subsequent final incremental link passed).
- `node --test "port/web/tests/*.test.js"`: **14/14 passed**.
- `python -m pytest -q tools/test_web_build.py`: **10/10 passed** using dude's Python 3.12
  virtualenv because this host has neither a `python` shim nor system pytest.
- `uv run ruff check m8py tests`: **passed**.
- `uv run pytest -q`: **57/57 passed**.

### Headless Chrome

Chrome ran with a fresh persistent profile, SwiftShader flags, fake media devices, localhost port
8010, and the worktree site's `maps` symlink to the specified existing map directory. The isolated
mock stack used `ws://127.0.0.1:18191/game` and `/mic`; the real running m8py at
`100.126.232.8:8091` / TCP 47800 was never contacted or restarted.

Observed flow:

1. Fresh profile imported 24 map files (1.86 GB) and auto-started the already-permitted mic.
2. One grid click started `b30` and reached controllable first-person gameplay.
3. An `OLD_MEMORY_MARKER` was inserted into the mock brain.
4. Returning to the launcher and clicking `a30` produced the exact `new_game` trace event.
5. After adding `AFTER_RESET_MARKER`, the brain prompt contained the new marker and did not contain
   `OLD_MEMORY_MARKER`; checkpoint storage had also been cleared.
6. `a30` reached controllable first-person gameplay with its opening cinematic skipped.

Timings are click to the first post-cinematic companion state (the companion sends no state while
`cinematic_in_progress()`, making this a player-control boundary):

| Level | Skip setting | Time to control |
| --- | --- | ---: |
| `a30` | on | **5.595 s** |
| `a30` | off | **133.507 s** |
| `b30` | on | **87.364 s** |
| `b30` | off | **89.678 s** |

Screenshots:

- `/home/minjune/m8work/logs/levels-grid.png` — ready launcher, ten-level grid, mic Connected.
- `/home/minjune/m8work/logs/levels-b30-skip-on.png` — `b30` first-person gameplay.
- `/home/minjune/m8work/logs/levels-b30-skip-off.png` — disabled-setting comparison.
- `/home/minjune/m8work/logs/levels-a30.png` — `a30` first-person gameplay after the skipped intro.

## Commits and patch

- OpenCE `m8-web-skip`: `2e10d6141e534a0ab70cd7a1e949c3216f967f42`
  (`Start campaign levels fresh from the web launcher`)
- m8py `claude/wizardly-bohr-5h3qa8`:
  `bff2bfcb53f56c526b2ac06d0f52c4b358152f93`
  (`Reset companion memory for fresh campaign levels`)
- OpenCE diff from `31d9fb19043af9b31a81446bef8f5356233c39cc`:
  `/home/minjune/m8work/codex-out/opence-levels.patch`
- Patch SHA-256: `d2ac57507b2b5d9e7de33535c1369569770226fdd06cc0ec639d6587bfef52d9`

Both repository worktrees are clean. Nothing was merged into `m8-web`, packaged, deployed, or
connected to the user's live companion.
