# m8 / OpenCE native Linux build and protocol report

Date: 2026-10-27  
Host: Ubuntu 22.04 x86-64, NVIDIA driver 580  
OpenCE base: `8102e711`  
Local branch: `m8-linux`

## 1. Build status

### Result

**Success.** The native Linux release binary built and passed OpenCE's link checker:

```text
/home/minjune/m8work/halo/build/linux/halo
```

It is a 35 MB, non-PIE ELF32 little-endian Intel 80386 executable, dynamically linked with interpreter `/lib/ld-linux.so.2`. Build ID: `c6d4669ac35c3536c6129e945e7fc31d7799de56`; SHA-256: `4ded193e0207422ea306edc2543108cbb79310302aec2447e6f3ffc4dadefead`. The bundled native 32-bit `build/linux/libSDL3.so.0` is 3.8 MB and has SHA-256 `f6f08ee8bd2b3bea24462618626f4810a4490524c24f27cb3c2ca304db7fd7c9`.

`llvm-readelf-22` confirmed ELF32/i386, a real `DT_RPATH=$ORIGIN`, `DT_NEEDED=libSDL3.so.0`, and maximum required glibc symbol version `GLIBC_2.29`. A final `ninja -n linux` reported `no work to do`. OpenCE's `tools/linux_link_check.py` ran successfully as part of the link. The game itself was deliberately not executed.

The Linux target is a native **32-bit x86 ELF** even on this x86-64 host. OpenCE keeps the game 32-bit because map, tag, and saved-game data contain 32-bit pointers. It renders through OpenGL 4.5, uses SDL3 for window/input/audio, and accepts keyboard, mouse, and SDL gamepads.

The build was configured in OpenCE's documented portable mode. This does not make a containerized or emulated build: it still produces the native `i686-linux-gnu` executable. Portable mode was appropriate on Ubuntu 22.04 because Jammy has no `libsdl3-dev:i386`; OpenCE instead downloads its pinned Debian 11 i386 sysroot, builds SDL 3.4.16 itself, puts `libSDL3.so.0` beside `halo`, and gives the executable an `$ORIGIN` RPATH. It also avoids requiring this build host's glibc version on the eventual run host.

### Exact source and build commands

```bash
cd /home/minjune/m8work
git clone https://github.com/OpenCommunityEdition/OpenCE.git /home/minjune/m8work/halo
git -C /home/minjune/m8work/halo checkout 8102e711
git -C /home/minjune/m8work/halo switch -c m8-linux
git -C /home/minjune/m8work/halo apply --whitespace=nowarn /home/minjune/m8work/m8/games/halo/m8.patch

# Preserve the supplied m8 change as the baseline, separate from Linux fixes.
cd /home/minjune/m8work/halo
git add -A
git commit -m "Apply m8 Halo companion patch"

# apt.llvm.org's llvm.sh added the Jammy LLVM 22 repository and key.
curl -fsSL https://apt.llvm.org/llvm.sh -o /home/minjune/m8work/codex-out/llvm.sh
chmod +x /home/minjune/m8work/codex-out/llvm.sh
sudo /home/minjune/m8work/codex-out/llvm.sh 22

# After a pre-existing apt job released the apt lock:
sudo apt-get update
sudo apt-get install -y clang-22 lld-22 cmake pkg-config libwayland-bin ninja-build \
  gcc-multilib libc6-dev-i386 libgl1:i386 libx11-6:i386 libxext6:i386 \
  libpulse0:i386 libasound2:i386

# Jammy's CMake 3.22 does not support OpenCE's required `cmake --fresh`.
python3 -m pip install --user 'cmake>=3.24,<4'

cd /home/minjune/m8work/halo
python3 configure.py --release --portable --linux-cc clang-22
ninja -v linux
```

`configure.py` defaults to PGO `use`. clang 22 is needed to read OpenCE's committed `pgo/halo_linux.profdata`; older clang builds without that profile. The selected compiler was apt.llvm.org's Ubuntu clang 22.1.8, with LLD 22.1.8. OpenCE's Python build helpers otherwise use the standard library, but this host needed the `cmake` 3.31.10 Python wheel because Ubuntu 22.04's packaged CMake 3.22 rejected OpenCE's `--fresh` option. The first build attempt stopped there; after installing newer CMake, the unchanged tree built successfully.

### Packages

Explicit apt request:

- Newly installed for this task: `clang-22`, `lld-22`, `gcc-multilib`, `libc6-dev-i386`, `libpulse0:i386`, and `libasound2:i386`, plus their apt-resolved LLVM, multilib, and i386 dependencies.
- Already installed and retained: `cmake`, `pkg-config`, `libwayland-bin`, `ninja-build`, `libgl1:i386`, `libx11-6:i386`, and `libxext6:i386`.
- Already present and important for real NVIDIA rendering: `libnvidia-gl-580:i386` 580.95.05.
- User-level Python package installed: `cmake` 3.31.10 (the system CMake 3.22 remains installed).

OpenCE's portable build separately fetched its checksum-pinned Debian i386 sysroot packages and SDL 3.4.16 source into `build/linux/third_party`; those are build-tree inputs, not system package installations.

The apt update reported an unrelated stale Spotify repository signing-key warning. The Ubuntu and apt.llvm.org indexes used here updated successfully.

## 2. m8 patch application and Linux fixes

`git apply --whitespace=nowarn` completed successfully against `8102e711`. There were **no rejects**, no `.rej` files, and `git diff --check` reported no whitespace errors. The applied m8 baseline is local commit:

```text
69f70b48 Apply m8 Halo companion patch
```

No Linux source fix was needed. In particular, `companion.c` and `mate_link.c` compiled under clang 22 and the full-LTO/PGO link completed as supplied. The only build correction was installing a sufficiently new CMake; it did not modify the repository. Therefore there is no second source commit after `69f70b48`, `git status` is clean, and the Linux-only patch is intentionally zero bytes.

Exported patches:

- `/home/minjune/m8work/codex-out/opence-m8-linux.patch` — full tree difference from `8102e711`, generated with `git diff --binary 8102e711` so the m8 PNG assets remain applyable.
- `/home/minjune/m8work/codex-out/opence-linux-fixes.patch` — only changes after the m8 baseline commit (`git diff --binary 69f70b48`); this is empty if no Linux correction was needed.

## 3. Supplying game data

No game data was downloaded or created during this work.

### What OpenCE accepts

OpenCE needs a data root containing a `maps/` directory from the Xbox release of Halo: Combat Evolved. It accepts either:

1. A user-supplied Xbox disc image, selected through the first-start GUI. The file-picker filter offers `.iso` and `.xiso`, plus “All files.” The content must be an Xbox XDVDFS image; the extractor understands a plain XISO game partition and whole-disc GLOBAL/XGD1/XGD3 offsets. Any regional/version disc is supported. A PC Halo installation or an ordinary ISO filesystem is not a substitute.
2. An already-extracted folder. Point OpenCE at the **parent directory containing `maps/`**, not at `maps/` itself. This avoids the first-start picker.

The extractor verifies that the image has an XDVDFS `maps` directory and that it contains `ui.map`. It copies the disc's `maps/` only. It first writes `maps.partial`; after a complete successful copy it renames that directory to `maps`. An interrupted copy leaves `maps.partial`, and the next start asks again.

### First-start GUI path

1. Start `/home/minjune/m8work/halo/build/linux/halo` from a graphical X11 or Wayland session.
2. When told that game data was not found, choose **Yes**.
3. Select the user's own `.iso` or `.xiso` in the SDL file picker.
4. Leave the extraction progress window open. OpenCE copies about 2 GB to `/home/minjune/m8work/halo/build/linux/maps/` (next to the executable), then starts the game.
5. After a successful extraction, the source image is no longer needed by OpenCE.

Choosing **No** exits cleanly. Cancelling the file picker returns to the question. There is no disc-image command-line option in this revision. The prompt, picker, and progress UI initialize SDL video and therefore need a working graphical display. For unattended setup, provide an already-extracted `maps/` folder instead.

### Data-root search order

At startup OpenCE searches, in order:

1. `paths.data` from `build/linux/config.toml` (or the `HALO_DATA_ROOT` environment override).
2. The current working directory, if it contains `maps/`.
3. The executable's directory, if it contains `maps/`.
4. `assets/` under the current directory.
5. The repository `assets/` inferred from the executable's `build/linux/halo` path.

Practical folder-based setup:

```bash
# Option A: put the user-owned extracted data beside the binary
/home/minjune/m8work/halo/build/linux/maps/ui.map

# Option B: leave it elsewhere and launch with its parent as the data root
HALO_DATA_ROOT=/absolute/path/to/halo-data \
  /home/minjune/m8work/halo/build/linux/halo
```

Do not put or download any proprietary game files into the source checkout unless the user supplies them.

## 4. Running the Linux build

### Normal launch

The least surprising working directory is the executable directory:

```bash
cd /home/minjune/m8work/halo/build/linux
./halo
```

`brokers.txt`, `libSDL3.so.0`, and the binary live there. On first execution, OpenCE creates `config.toml` beside the executable; it is always read/written there, independent of the shell's working directory. Save/user data defaults to `$XDG_DATA_HOME/halo-linux` or `~/.local/share/halo-linux`; `paths.saves`/`HALO_SAVE_ROOT` can override it. The game log is `debug.txt` in the selected data root.

Start m8 first if companion behavior is wanted. m8 listens on `127.0.0.1:47800`; the game connects and will retry if m8 starts or restarts later.

### Display and window mode

No display manager is required, but a graphical server/session is. For normal play on the DP-4 monitor, start or use an Xorg session or a Wayland compositor that owns that output, then launch from a terminal carrying its environment:

- X11 needs a valid `DISPLAY` and normally `XAUTHORITY`.
- Wayland needs `XDG_RUNTIME_DIR` and `WAYLAND_DISPLAY`. The bundled SDL can use native Wayland when the compositor supplies the needed protocols; otherwise XWayland/X11 is suitable.
- DP-4 selection/layout is the responsibility of Xorg/compositor configuration. OpenCE uses SDL's primary display; it has no `DP-4` command-line selector.

The current non-graphical shell has no `DISPLAY`, `WAYLAND_DISPLAY`, or `XDG_RUNTIME_DIR`, so launching from it would not be a normal playable start. No display manager or game process was started during this task.

Window settings are in `[display]` in `build/linux/config.toml` and have environment overrides:

- Default: borderless at the primary desktop's native resolution (`display.mode = ""`, `display.fullscreen = true`).
- Window: `HALO_DISPLAY_MODE=windowed HALO_WINDOW_SIZE=1280x720 ./halo`.
- Exclusive fullscreen: `HALO_DISPLAY_MODE=fullscreen ./halo`.
- F11 toggles window/fullscreen; F12 releases/captures the mouse.

The renderer needs an OpenGL 4.5 context. The installed 32-bit NVIDIA 580 GL library satisfies the client-side library requirement for the RTX system without touching the root-owned vLLM process.

### Audio and input

SDL3 dynamically loads available 32-bit audio clients. Letting SDL choose is recommended; it can use PipeWire, PulseAudio, or ALSA. This host now has the 32-bit PulseAudio and ALSA client libraries. In an actual desktop session, make sure the user's PipeWire/PulseAudio socket and `XDG_RUNTIME_DIR` are visible. Optional diagnosis/forcing examples are:

```bash
SDL_AUDIODRIVER=pipewire ./halo
SDL_AUDIODRIVER=pulseaudio ./halo
HALO_NO_AUDIO=1 ./halo
```

Keyboard/mouse work directly through SDL. Defaults include WASD, mouse aim/fire, E action, R reload, Space jump, Escape pause, backtick console, and **M** to toggle m8's microphone. The first SDL gamepad joins controller 1; with local split-screen and only one gamepad, keyboard/mouse remain controller 1 and that gamepad becomes controller 2. Bindings and audio device names can be changed in menus or `config.toml`.

### Headless and Xvfb feasibility

OpenCE has a purpose-built no-window path, which is preferable to Xvfb for automated simulation:

```bash
cd /home/minjune/m8work/halo/build/linux
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  HALO_NULL_RENDERER=1 HALO_NO_AUDIO=1 \
  HALO_DATA_ROOT=/absolute/path/to/halo-data HALO_EXIT_AFTER=60 ./halo
```

This was not executed, per the instruction not to run the game. `HALO_NULL_RENDERER=1` makes Direct3D initialize without a window and draws nothing; the SDL dummy video driver avoids needing X11/Wayland. Pre-supplied `maps/` is mandatory for this use: first-start extraction deliberately does not offer its GUI in hidden/automated modes. A suitable `init.txt` in the data root can issue game console commands such as loading a map.

Important limitation: null-renderer runs cannot produce kind-4 companion view frames, because those are read from the OpenGL back buffer during Present. State/action/TCP testing can still be useful.

Xvfb is possible only if its GLX/Mesa path can actually expose the required OpenGL 4.5 context; many Xvfb configurations do not. It would normally render through 32-bit Mesa llvmpipe rather than the RTX. It is therefore less reliable and unnecessary for nonvisual automation. For testing view capture, use a real Xorg/Wayland/Xwayland session (or a deliberately configured virtual X server with verified GL 4.5), not `HALO_NULL_RENDERER`.

## 5. Companion protocol reference

This section describes the implementation in `port/linux/game/companion.c`, `port/linux/src/mate_link.c`, and, where needed to disambiguate message intent, m8's `m8/src/link.rs`/`brain.rs`/`speak.rs`.

### Transport, connection, and framing

- m8 is the TCP **server**, bound by default to `127.0.0.1:47800`.
- OpenCE is the TCP **client**. Host and port are hardcoded as `127.0.0.1` and `47800` in this patch.
- `mate_link_start()` is called from the campaign companion update and starts one background connection thread once.
- Every attempt creates a TCP socket and connects. A successful connection enables `TCP_NODELAY`. On EOF/read failure, the game logs disconnection, clears the active socket and voice, closes the socket, waits **2,000 ms**, and tries again. Failed initial connects also wait 2,000 ms. There is no exponential backoff.
- m8 sends its `hello` immediately after accepting. OpenCE does not send a hello of its own.
- All frames start with a 5-byte header: one-byte kind followed by an unsigned 32-bit **big-endian** payload length. Payload bytes immediately follow.

| Kind | Direction | Payload |
|---:|---|---|
| 1 | both | UTF-8 JSON object (the game-side matcher actually treats received bytes as a NUL-terminated string) |
| 2 | m8 → game | raw mono signed 16-bit little-endian PCM at the rate in `hello` |
| 3 | game → m8 | `u16be json_length`, JSON metadata, then mono signed 16-bit little-endian PCM |
| 4 | game → m8 | `u16be json_length`, JSON metadata, then packed RGB bytes |

Game-to-m8 sends are serialized with a mutex, but the C implementation calls `send` once per header/part and does not loop on short writes. A faithful fake should use `write_all`/equivalent and should tolerate fragmented TCP reads. Incoming JSON and audio payloads are allocated from the advertised length. Normal peers must keep lengths sane.

Received JSON is put into a 32-entry FIFO for the game tick, each entry truncated to at most 2,047 bytes plus NUL. When the FIFO is full, another ordinary JSON message is dropped. `hello`, `stop_audio`, and `audio_end` do their immediate link/audio work before or instead of queueing as described below.

### JSON sent by the game

#### `state`

Emitted every 15 game ticks (twice a second at Halo's 30 Hz), provided a living local player is in a single-player/non-distributed-client campaign and no cinematic is in progress. It is also sent immediately before any aggregated `event`, so two states can occur in one tick.

```json
{
  "type": "state",
  "game": "Halo: Combat Evolved",
  "player_name": "Chief",
  "level": "a30",
  "in_combat": true,
  "on_radio": false,
  "state": "Kevin: ...",
  "actions": []
}
```

Field semantics:

- `game` is the fixed literal `Halo: Combat Evolved`.
- `player_name` is the fixed literal `Chief`. m8 uses its own configured player name when expanding `{player}`; the game nevertheless always transmits this field.
- `level` is the last path component of the loaded scenario tag, such as `a10`, `a30`, or `d40`.
- `in_combat` is `true` whenever the game has found at least one living enemy unit within 45 world units (about 137 m) of Kevin. Visibility is not required, so this is broader than “currently exchanging fire.” At most 12 nearest enemies are retained.
- `on_radio` is the most recently calculated voice-placement mode: true while Kevin is alive and his voice would be radio-processed because he is beyond `companion.radio_distance` (default 25 m), a structure blocks line of sight, or there is no usable local camera. It is not simply “audio is currently playing.”
- `state` is prose generated as detailed below. It deliberately contains the `{player}` placeholder.
- `actions` contains only actions currently available. An absent action is not legal at that instant.

Alive `state` prose has this exact shape:

```text
Kevin: <health>, <shield>, <weapon/inventory><doing>. {player}: <close by|nearby|far away> <direction>, <health>, <shield>. Enemies: <enemy>; <enemy>.
```

Kevin health words are `unhurt` (≥.95), `a bit hurt` (≥.60), `hurt` (≥.30), or `badly hurt`. Shield words are `shields full` (≥.95), `shields holding` (≥.50), `shields low` (>0), or `shields down`.

Inventory prose is:

- `no weapon`, or `holding a[n] <tag name> (<N> rounds loaded|magazine empty, <spare ammo|no spare ammo>)`;
- then `, a[n] <other weapon> on his back (<N> rounds loaded, <spare ammo|no spare ammo>)`, or `, no second weapon`;
- then `, <N> frag and <N> plasma grenades`;
- optionally `, riding in a <vehicle>` and `, flashlight on`.

The `<doing>` suffix can contain `, following {player}`, `, rushing in`, `, taking cover`, `, falling back`, `, going to pick up a weapon`, or `, going to get in a vehicle`; then optionally `, shooting at {player}` or `, shooting at the <kind>`, `, crouching`, and `, holding his fire`. Holding position itself adds no phrase.

The player's distance from Kevin is `close by` at ≤6 m, `nearby` at ≤25 m, else `far away`. Directions are `ahead`, `behind`, `to the left`, or `to the right`, relative to Kevin's current aim.

Each enemy is:

```text
<kind>[ aboard a[n] <vehicle>] <close|at mid range|far away> (<integer metres> m) <direction>, <in sight|out of sight>, <health>[, <shield>]
```

Range words are close at ≤10 m, mid range at ≤25 m, else far away. Metres are truncation of world-units × 3.048. Shield prose is omitted when the enemy has no positive shield. When Kevin is dead, state is instead:

```text
Kevin is dead and will be back soon. {player}: <health>, <shield>.
```

and `actions` is empty.

#### Action object schema and complete catalog

Ordinary action:

```json
{"name":"shoot","description":"shoots at an enemy","options":{"123":"grunt close (8 m) ahead, in sight, unhurt"}}
```

- `name` is the wire action name.
- `description` is third-person text after the mate's name; `{player}` is a placeholder.
- `options`, when present, maps string IDs to prose labels. Enemy/weapon/vehicle IDs are the low 16 bits of the current game datum index, rendered as decimal strings. Options are a snapshot, not durable handles.
- An action whose target list is empty is omitted.

Search/report action:

```json
{
  "name":"search_weapons",
  "description":"looks around for weapons",
  "result":"shotgun (4 m) ahead; pistol (7 m) to the left",
  "then":[{"name":"pick_up","description":"picks up a weapon","options":{"88":"shotgun (4 m) ahead"}}]
}
```

`result` is `none nearby` or a semicolon-separated list. `then` is absent when nothing was found. m8 sends the search action (which the game intentionally treats as a no-op because the result already came in state), adds the result to memory, then may send one listed `then` action.

View action:

```json
{"name":"go_to","description":"goes to a spot {player} can see","view":"choose"}
```

`view` is `choose` for `go_to` or `describe` for `look`. m8 first requests a kind-4 view. For `choose`, it may then send the chosen spot ID as the action's `option`. For `describe`, the `look` action itself is not sent after the view in the current m8 code; it is a perception result only.

Complete dynamically offered list:

| Name | Exact description | Availability / extra fields |
|---|---|---|
| `follow` | `follows {player}` | omitted if already following |
| `stay` | `stays where he is` | omitted if already holding |
| `shoot` | `shoots at an enemy` | `options`: all known enemies; omitted if none |
| `hold_fire` | `stops shooting at {player}` or `stops shooting at the <kind>` | only with a current target |
| `shoot_chief` | `turns his gun on {player}` | unless Chief is already the target |
| `rush` | `rushes an enemy` | enemy `options`; enemies present and Kevin not in a vehicle |
| `cover` | `takes cover` | enemies present and not in a vehicle |
| `fall_back` | `falls back` | enemies present and not in a vehicle |
| `frag_grenade` | `throws a frag grenade` | enemy `options`; has frag grenade and not in vehicle |
| `plasma_grenade` | `sticks a plasma grenade on an enemy` | enemy `options`; has plasma grenade and not in vehicle |
| `melee` | `punches an enemy` | options only for enemies within .7 world unit (~2.13 m); not in vehicle |
| `switch_weapon` | `switches to his <other weapon>` | has a second weapon |
| `get_out` | `gets out of the vehicle` | in a vehicle |
| `search_weapons` | `looks around for weapons` | always while on foot; `result`, optional `then: pick_up`; scans up to 6 nearest loose weapons within 4 world units (~12.2 m) |
| `pick_up` | `picks up a weapon` | only inside `search_weapons.then`; object `options` |
| `search_vehicles` | `looks around for vehicles` | always while on foot; `result`, optional `then: get_in`; scans up to 6 nearest vehicles within 8 world units (~24.4 m) |
| `get_in` | `gets in a vehicle` | only inside `search_vehicles.then`; object `options` |
| `go_to` | `goes to a spot {player} can see` | on foot; `view:"choose"` |
| `go_aim` | `goes where {player} is aiming, <N> m from {player}` | on foot, only when the current center ray finds valid ground |
| `jump` | `jumps` | on foot |
| `crouch` / `stand_up` | `crouches` / `stands up` | on foot; exactly one according to current toggle |
| `look` | `takes a look at something {player} wants him to see` | always; `view:"describe"` |
| `flashlight` | `switches his flashlight on` or `switches his flashlight off` | always |

#### `event`

```json
{"type":"event","text":"Kevin's shields broke. Kevin is taking heavy fire."}
```

No `react` field is emitted by this Halo patch, so m8 defaults it to true. Multiple detections in a tick are concatenated into one space-separated `text`. Before it sends this event, the game sends a fresh state.

Detected event clauses and triggers:

- `Enemies came into view: <grouped description>.` — first visible enemies after no current contact; contact resets only once no enemies remain nearby. Foot enemies group by kind/direction; vehicle occupants group under one vehicle.
- `<riders> got off the <vehicle> <direction>.` or `<riders> got off their vehicle.` — a previously tracked enemy rider is alive and now unparented.
- `Kevin killed a[n] <kind>.`, `{player} killed ...`, or `Someone killed ...` — an enemy known on the prior tick is now dead; attribution is its newest attacker record.
- `{player} shot Kevin.` — a newer player attacker timestamp appears on Kevin.
- `Kevin's shields broke.` — previous shield >0, current shield ≤0.
- `Kevin is badly hurt.` — body vitality crosses from ≥.30 to <.30.
- `Kevin is taking heavy fire.` — over the half-second sample interval, shields fell by at least .30 but remain >0.
- `{player}'s shields went down.` — player shield crosses >0 to ≤0.
- `{player} is badly hurt.` — player body vitality crosses ≥.30 to <.30.
- `{player} picked up a <weapon>.` — a current inventory slot contains an object index absent from all four previous slots.
- `{player} got in the <vehicle>.` / `{player} got out of the <vehicle>.` — parent vehicle changed and the relevant object still resolves.
- `New objective: <text>.` — nonempty HUD objective changed. UTF-16 is reduced to printable ASCII, `|n` becomes space, quotes become apostrophes, backslashes become `/`, and repeated spaces are collapsed.
- `{player} died.` — sent once on transition to a present-but-dead player unit.
- `Kevin died.` — sent when his previously known body can no longer be found alive. Respawn is scheduled 10 seconds later.

Event history resets when the game clock moves backwards (new level/load). No state/events are produced during cinematics; the dialogue channel covers scripted speech there.

#### Save/load, direct, mic, and settings

```json
{"type":"saved","id":"a30:18452"}
{"type":"loaded","id":"a30:18452"}
```

The ID is `<scenario basename>:<game_time_tick>`. The saved game carries game time, so a checkpoint's `saved` and later `loaded` IDs match. These messages are suppressed in multiplayer/game-engine mode and on a distributed client. m8 snapshots memory on `saved`; on `loaded`, it restores the newest matching snapshot or clears memory if it never saw that ID.

```json
{"type":"direct","text":"you are dead"}
```

Generated by the in-game console command `kevin <text>`. It is sent only if connected. Quotes and backslashes are JSON-escaped and control bytes are omitted. m8 treats it as a reactive `Game master: ...` event.

```json
{"type":"mic","muted":false}
```

Sent on each M-key mute toggle and once on every new connection. Muting affects m8's physical microphone listener, not Halo voice-chat capture.

```json
{"type":"settings","speech_cooldown":5.00}
```

Sent on connection and whenever the clamped setting changes. Range is 0–600 seconds. This is the only setting sent to m8; world/radio volume and radio distance remain game-side.

### JSON sent by m8 and what OpenCE actually does

OpenCE does **not** parse received JSON structurally. It searches for exact compact substrings such as `"type":"action"`, `"action":"shoot"`, and `"option":"`. Whitespace between key/colon/value would stop a match. m8's `serde_json::Value::to_string()` emits the compact form. A fake m8 should do the same.

#### `hello`

```json
{"type":"hello","name":"Kevin","sample_rate":24000}
```

Immediately handled on the link thread. If `sample_rate` is present, `atoi` sets the source voice rate; otherwise it stays at its prior/default 24,000 Hz. `name` is logged nowhere and does not rename the in-game Kevin. The message is also queued and then ignored by companion gameplay. Send a positive nonzero rate.

#### `action`

```json
{"type":"action","action":"shoot","option":"123"}
```

`option` must be a JSON string. For enemy/weapon/vehicle actions, it is parsed as decimal and resolved against the **current** arrays by low-16-bit ID, searching enemies first, then nearby weapons, then nearby vehicles. A stale/unknown ID resolves to `NONE`.

Effects:

- `follow` / `stay`: change movement order while retaining current target and hold-fire state.
- `shoot`: select the resolved target, clear hold-fire, and enable continuing engagement; after the target dies, Kevin can select the nearest visible enemy until told to hold fire.
- `hold_fire`: clear target, set hold-fire, stop engagement.
- `rush`: select advance order and target, clear hold-fire, enable engagement.
- `cover` / `fall_back`: change movement order, retaining target/hold-fire.
- `go_to`: interprets `option` directly as a **1-based view spot ID**, not an object ID. If within the latest captured `1..spot_count`, Kevin holds that stored world point.
- `go_aim`: ignores object resolution and recomputes the center-screen ground point when the message is processed; if valid, Kevin holds it.
- `shoot_chief`: targets the current local player and clears hold-fire.
- `switch_weapon`, `jump`, `flashlight`, `get_out`: start the corresponding one-shot control action.
- `frag_grenade` / `plasma_grenade`: start a grenade action toward the resolved target and select grenade type.
- `melee`: starts a melee action toward the resolved target.
- `crouch` / `stand_up`: set or clear the persistent crouch toggle.
- `pick_up` / `get_in`: only act if the object ID still resolves. Store it as the goal object and walk toward it under the corresponding order.
- `search_weapons`, `search_vehicles`, and `look`: no matching gameplay branch; these are intentionally informational/perception actions. Unknown action names are likewise ignored.

String matching is an `if/else if` chain in the order above. Do not include multiple action substrings in one message.

#### `view`

```json
{"type":"view"}
```

Sets a one-shot flag. At the next OpenGL Present, the game captures and sends kind 4. If rendering is absent/null or Present never occurs, no view frame is sent. Multiple requests before the game tick coalesce into the same boolean request.

#### `say` and `heard`

```json
{"type":"say","text":"Move up!"}
{"type":"heard","text":"Cover me."}
```

Both enter the 32-message game FIFO, but `companion_handle_messages()` has no branch for them, so OpenCE discards them with no visual, animation, or gameplay effect. `say` is sent by m8 as each TTS sentence starts; actual speaking behavior is driven by kind-2 audio. `heard` records m8's microphone transcription in the brain/feed; the game does not need it.

#### `stop_audio` and `audio_end`

```json
{"type":"stop_audio"}
{"type":"audio_end"}
```

- `stop_audio` acts immediately on the link thread, is **not queued**, empties the resampled ring, clears playing/queued state, unkeys the radio if keyed, and flushes the DirectSound stream. m8 sends it for barge-in, save-load interruption, or when a new generated line supersedes still-playing audio.
- `audio_end` sets `line_over` immediately and is then also queued (gameplay ignores the queued copy). If no audio remains it unkeys at once; otherwise it unkeys when the buffered voice drains. This marks a logical line end, not an audio payload.

### Kind-2 voice audio and placement

Kind-2 payload is headerless mono signed i16 little-endian PCM at `hello.sample_rate`. OpenCE linearly resamples it to 48 kHz float audio into a 60-second ring. It starts playback after 2,400 output samples (50 ms) are buffered. New samples beyond the 60-second capacity are dropped. The DirectSound stream is maintained around 50–100 ms ahead of the mixer.

The resampler's phase/last sample are not reset by `stop_audio`, reconnect, or a new hello. A faithful test peer should send normal contiguous chunks and a consistent rate for a connection.

Each game tick places the stream as follows:

- **World voice** when Kevin is alive, a local camera exists, distance is within `companion.radio_distance`, and no front-facing structure collision blocks camera-to-head line of sight. It is a DirectSound 3D stream at Kevin's head in listener space, with the map dialogue class's minimum distance, obstruction, occlusion, wet/dry reverb behavior, dialogue ducking/class gain, and `companion.voice_volume`.
- **Radio voice** otherwise: 3D is disabled (centered/dry), volume uses dialogue gain × 4 × .375 × `companion.radio_volume`. The signal eases into two 300 Hz high-pass plus two 3 kHz low-pass filters, adds light hiss, drives a soft clip, and blends with the dry voice. Key-down adds 60 ms of static; line end/cutoff unkey adds 180 ms.

While voice audio is playing and Kevin has no visible combat target, his body looks toward the player. `say` JSON is not what triggers that behavior.

### Kind-3 game dialogue (“hear”) frames

Payload layout:

```text
u16be metadata_json_length
metadata JSON bytes
mono signed i16 little-endian PCM bytes
```

Metadata example:

```json
{"speaker":"Cortana","radio":true,"react":true,"sample_rate":22050}
```

Capture conditions are exact:

- Sound class is one of scripted-dialog-to-player, scripted-dialog-to-other, or scripted-dialog-force-unspatialized.
- Permutation compression is Xbox ADPCM (`compression == 1`), the only captured format.
- Single-player/non-distributed-client and m8 is currently connected.
- The compressed permutation is decoded. Stereo is averaged to mono. `sample_rate` is 22,050 or 44,100 Hz from the sound definition.

`radio` is true only when `source_identifier == NONE` and no cinematic is in progress. `react` is false for cinematic dialogue and true otherwise, allowing m8 to remember cutscene lines without answering them.

Speaker is inferred from the last underscore-separated sound-tag word containing letters, lowercased and truncated at its first digit/space. Mappings are:

- `cortana`, `cor` → `Cortana`
- `captkeyes`, `keyes` → `Captain Keyes`
- `sarge`, `sgt` → `the Sergeant`
- `lifeboatpilot`, `lif` → `the lifeboat pilot`
- `pilot` → `the pilot`
- `flightofficer` → `the flight officer`
- `chief`, `che` → `{player}`
- `cryotech`, `cryoassist`, `tec`, `ass`, `crewman` → `a crewman`
- anything else → `a marine`

m8 converts PCM to float, resamples to 16 kHz for STT, transcribes immediately, but delays injecting the resulting event until the original line's duration has elapsed. It appends ` over the radio` to speaker text when applicable.

### Kind-4 player view frames

Payload layout:

```text
u16be metadata_json_length
metadata JSON bytes
width * height * 3 packed RGB bytes, rows from the top
```

Metadata:

```json
{
  "width": 960,
  "height": 540,
  "spots": [
    {"id":1,"x":0.063,"y":0.475,"metres":18},
    {"id":2,"x":0.188,"y":0.688,"metres":11}
  ]
}
```

Resolution comes from the actual game back buffer. Let `step = ceil(backbuffer_width / 1024)`. Sent dimensions are `floor(width/step)` × `floor(height/step)`. Every output RGB pixel is the box average of one `step × step` source square. Thus widths ≤1024 are unchanged; 1920×1080 becomes 960×540; 2560×1440 becomes 853×480, with incomplete right/bottom remainders omitted.

Spots use the interpolated local-player camera and rendered FOV. The candidate grid is 8 columns × 5 rows:

- projected x: −0.875 … +0.875, reported normalized x: 0.0625 … 0.9375;
- projected y: −0.05 … +0.80, reported normalized y: 0.475 … 0.900;
- rows are scanned top-to-bottom and columns left-to-right.

For each ray, the game looks up to 40 world units (~121.9 m), colliding with level structure and sight-blocking objects while ignoring the player's unit. A hit is accepted directly if it is structure with upward normal z ≥0.6. For a wall/object hit, it steps 0.6 world unit back, 0.5 up, casts 4 units down against structure, and accepts a floor whose normal z ≥0.6. Invalid candidates are omitted.

IDs are assigned **sequentially only to accepted points**, starting at 1; they do not identify fixed grid cells and can shift every frame. `x`/`y` print to three decimals. `metres` is the truncated camera-to-ground distance ×3.048. At most 40 spots are present. The code does not perform a companion path-reachability test before advertising a spot.

For `go_to`, m8 overlays numbers locally in its saved PNG, asks its vision model to choose one of the supplied IDs (or 0), and sends the selected ID as a decimal string. The game uses the stored world coordinate from the most recently captured view.

### Reconstructed realistic `state` examples

These are valid reconstructions from the formatting/availability rules, not captured runtime logs. Datum IDs and inventory counts are illustrative.

Calm, following, no nearby enemies:

```json
{
  "type":"state",
  "game":"Halo: Combat Evolved",
  "player_name":"Chief",
  "level":"a10",
  "in_combat":false,
  "on_radio":false,
  "state":"Kevin: unhurt, shields full, holding an assault rifle (60 rounds loaded, spare ammo), a pistol on his back (12 rounds loaded, spare ammo), 2 frag and 0 plasma grenades, following {player}. {player}: close by ahead, unhurt, shields full. Enemies: none.",
  "actions":[
    {"name":"stay","description":"stays where he is"},
    {"name":"shoot_chief","description":"turns his gun on {player}"},
    {"name":"switch_weapon","description":"switches to his pistol"},
    {"name":"search_weapons","description":"looks around for weapons","result":"none nearby"},
    {"name":"search_vehicles","description":"looks around for vehicles","result":"none nearby"},
    {"name":"go_to","description":"goes to a spot {player} can see","view":"choose"},
    {"name":"go_aim","description":"goes where {player} is aiming, 14 m from {player}"},
    {"name":"jump","description":"jumps"},
    {"name":"crouch","description":"crouches"},
    {"name":"look","description":"takes a look at something {player} wants him to see","view":"describe"},
    {"name":"flashlight","description":"switches his flashlight on"}
  ]
}
```

Combat with a visible Elite and an out-of-sight Grunt, holding position and shooting:

```json
{
  "type":"state",
  "game":"Halo: Combat Evolved",
  "player_name":"Chief",
  "level":"a30",
  "in_combat":true,
  "on_radio":false,
  "state":"Kevin: a bit hurt, shields low, holding a plasma rifle (magazine empty, no spare ammo), no second weapon, 1 frag and 2 plasma grenades, shooting at the elite, crouching. {player}: nearby behind, hurt, shields down. Enemies: elite close (9 m) ahead, in sight, a bit hurt, shields holding; grunt at mid range (18 m) to the left, out of sight, unhurt.",
  "actions":[
    {"name":"follow","description":"follows {player}"},
    {"name":"shoot","description":"shoots at an enemy","options":{"417":"elite close (9 m) ahead, in sight, a bit hurt, shields holding","522":"grunt at mid range (18 m) to the left, out of sight, unhurt"}},
    {"name":"hold_fire","description":"stops shooting at the elite"},
    {"name":"shoot_chief","description":"turns his gun on {player}"},
    {"name":"rush","description":"rushes an enemy","options":{"417":"elite close (9 m) ahead, in sight, a bit hurt, shields holding","522":"grunt at mid range (18 m) to the left, out of sight, unhurt"}},
    {"name":"cover","description":"takes cover"},
    {"name":"fall_back","description":"falls back"},
    {"name":"frag_grenade","description":"throws a frag grenade","options":{"417":"elite close (9 m) ahead, in sight, a bit hurt, shields holding","522":"grunt at mid range (18 m) to the left, out of sight, unhurt"}},
    {"name":"plasma_grenade","description":"sticks a plasma grenade on an enemy","options":{"417":"elite close (9 m) ahead, in sight, a bit hurt, shields holding","522":"grunt at mid range (18 m) to the left, out of sight, unhurt"}},
    {"name":"search_weapons","description":"looks around for weapons","result":"shotgun (4 m) to the right","then":[{"name":"pick_up","description":"picks up a weapon","options":{"88":"shotgun (4 m) to the right"}}]},
    {"name":"search_vehicles","description":"looks around for vehicles","result":"none nearby"},
    {"name":"go_to","description":"goes to a spot {player} can see","view":"choose"},
    {"name":"jump","description":"jumps"},
    {"name":"stand_up","description":"stands up"},
    {"name":"look","description":"takes a look at something {player} wants him to see","view":"describe"},
    {"name":"flashlight","description":"switches his flashlight on"}
  ]
}
```

Dead and currently in radio-placement conditions:

```json
{"type":"state","game":"Halo: Combat Evolved","player_name":"Chief","level":"c10","in_combat":false,"on_radio":false,"state":"Kevin is dead and will be back soon. {player}: badly hurt, shields holding.","actions":[]}
```

Even if the audio-placement calculation takes the radio branch while dead, `on_radio` is forced false because Kevin is not alive.
