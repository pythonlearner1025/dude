# Halo CE + m8 browser build report

## Result

The OpenCE web build now connects to m8py over `ws://.../game`, carries the native companion
frame stream unchanged, receives Kevin's PCM in the existing in-game positioned voice stream,
and returns WebGL2 back-buffer views through the existing kind-4 path. The launcher also has a
page-thread microphone streamer with browser echo cancellation, noise suppression, automatic
gain control, a level meter, status, remembered addresses, and reconnect.

The Mac distribution is ready at:

- `/home/minjune/m8work/web-dist/halo-m8-web/`
- `/home/minjune/m8work/web-dist/halo-m8-web.tgz`
- tarball SHA-256: `379df5f9d22fe4b663560d9af0f36336c76d498b1229ba81a6a323c8462865cd`

No Halo map/game data is in either artifact.

## Build

OpenCE requires Emscripten 6.0.10. It was installed in `/home/minjune/emsdk`:

```text
emcc (Emscripten gcc/clang-like replacement + linker emulating GNU ld) 6.0.10
```

Commands used for the initial release web build:

```sh
git clone https://github.com/emscripten-core/emsdk.git ~/emsdk
~/emsdk/emsdk install 6.0.10
~/emsdk/emsdk activate 6.0.10

cd ~/m8work/halo
python3 configure.py --release \
  --web-emcc /home/minjune/emsdk/upstream/emscripten/emcc
ninja web
```

The final configuration also names the installed versioned native compiler and keeps the
repository's pre-existing portable Linux setup:

```sh
python3 configure.py --release --portable --linux-cc clang-22 \
  --web-emcc /home/minjune/emsdk/upstream/emscripten/emcc
ninja web
ninja linux
```

Both final targets succeeded. The non-portable native attempt was not viable on this host because
there is no unversioned `clang` executable or 32-bit system SDL3 development package; the portable
build uses OpenCE's already-populated checked sysroot and SDL3, and completed successfully.

### What was already compiled, and what broke

`tools/web_build.py` globbed both `port/linux/game/companion.c` and
`port/linux/src/mate_link.c` into the web graph before these changes. The build log confirmed both
`companion.o` and `mate_link.o`.

The broken part was only transport: the native `mate_thread` opened TCP `127.0.0.1:47800` through
OpenCE's browser-local socket emulation. That address is inside the page's emulated network and
has no m8py listener. Voice creation/mixing and view capture were already compiled for the web:

- kind-2 PCM goes through `mate_add_voice`, the 48 kHz ring, and the existing DirectSound stream;
- the browser's SDL audio output is WebAudio, so the stream remains part of the game's mix;
- `write_companion_view` already reads the WebGL2 framebuffer before present; its `HALO_GLES`
  channel path produces RGB and calls `companion_view_taken`.

## OpenCE design and changed files

- `port/linux/src/mate_link.c`
  - Native builds retain the TCP thread unchanged.
  - `HALO_WEB` uses small C callbacks for open/close/data and a bounded byte-stream accumulator.
  - Incoming WebSocket messages may hold partial or multiple companion frames.
  - Outgoing JSON, dialogue-hearing, and view frames are assembled as exactly the native
    `[u8 kind][u32 BE length][payload]` stream.
- `port/web/src/web_library.js`
  - Owns the companion WebSocket on the page thread, matching OpenCE's existing broker WebSocket
    bridge and `PROXY_TO_PTHREAD` model.
  - Reconnects every two seconds forever and can change URL while the game is running.
  - Copies data across shared Wasm memory into the C stream parser.
- `port/web/site/index.html`, `style.css`, `app.js`
  - Add `?m8=` and `?mic=` handling, editable remembered URLs, mic on/off, level, and status.
  - The default mic URL is the m8 URL's host/port with path `/mic`.
  - `getUserMedia` requests `echoCancellation`, `noiseSuppression`, `autoGainControl`, and mono.
  - Audio is continuously resampled to 16 kHz and emitted as 320-sample (20 ms) little-endian
    signed-16 frames. It reconnects without stopping capture.
  - The captured track and game output are in the same browser audio environment, allowing the
    browser's acoustic echo canceller to use game/Kevin output as its reference.
- `tools/web_serve.py`
  - When copied beside `index.html`, its no-argument default is now that packaged directory.
  - Repository use still defaults to `build/web/site`.

OpenCE commit/branch:

```text
base m8-linux: 69f70b48902a1c5b52bfcb486157b27cc96af4f1
branch m8-web: bdaea890b93e0819a4ae5bb63784e71a6770d8a9
```

Exported diff: `/home/minjune/m8work/codex-out/opence-m8-web.patch` (relative to `m8-linux`).

## m8py

`m8py/listen.py` now mounts `/game` on the same aiohttp application and configured bind/port as
`/mic`. `m8py/link.py` accepts either TCP or WebSocket as the active game. A newly connected
transport closes the previous one, so the newest TCP or WebSocket connection wins. Outbound m8
frames select that active transport.

The WebSocket receiver explicitly treats binary messages as stream chunks: it buffers partial
headers/payloads, consumes multiple frames in one message, and rejects a declared frame above
64 MiB. The native TCP server continues to listen on `127.0.0.1:47800`.

`tests/test_listen.py` covers:

- a frame split between WebSocket messages;
- multiple frames in one WebSocket message;
- WebSocket replacing an existing TCP game;
- hello and outbound framing over WebSocket.

m8py commit on its existing branch:

```text
611e31f4f53ba7e3b110ae9821af4d6d53fc67b0
```

Validation:

```text
uv run ruff check m8py tests       All checks passed
uv run pytest -q                   56 passed
```

## Browser verification

The test used system Google Chrome through Playwright with:

```text
--use-angle=swiftshader
--enable-unsafe-swiftshader
--ignore-gpu-blocklist
--use-fake-device-for-media-stream
--use-fake-ui-for-media-stream
```

No model server, Xorg, Sunshine process, or GPU model workload was changed. The maps-folder input
imported the user's local `build/linux/maps` and reported `Copied 24 files`. The page passed all
five browser checks, mounted OPFS at `/data`, created the 2.1 GiB fixed Wasm memory, initialized
`OpenGL ES 3.0 (WebGL 2.0 Chromium)`, loaded `a10`, skipped the opening cinematic, and reached the
look-training room.

Relevant `logs/m8py.log` evidence:

```text
[game] connected 100.126.232.8 (websocket)
[game] received state
[sight] choose: Training diagnostic computer (1 m off) (1416 ms)
[game] sent audio frame (3840 bytes)
[stt] "Hold on." (57 ms)
```

The sight result proves the WebGL2 kind-4 view made the round trip to m8py. The audio log is an
actual kind-2 PCM frame sent to the active browser connection; the browser had already processed
the hello through the same C parser and existing game voice path. A synthetic remote microphone
source was streamed as 20 ms s16le messages and produced several `[stt]` entries. The page's own
fake-device microphone WebSocket was also visibly connected during the campaign pass.

Screenshots:

- `/home/minjune/m8work/logs/web-launcher.png`
- `/home/minjune/m8work/logs/web-mic-connected.png`
- `/home/minjune/m8work/logs/web-campaign.png`

Other checks:

```text
node --test "port/web/tests/*.test.js"       13 passed
python -m pytest -q tools/test_web_build.py  10 passed
ninja web                                    passed
ninja linux                                  passed (portable release)
packaged web_serve.py + curl                 HTTP 200 with COOP/COEP/CORP headers
```

After testing, the native Linux game was resumed and reconnected to m8py started by the required
`scripts/start-m8py.sh` launcher (retained by a transient user unit because automation shells reap
their orphaned children). m8py is currently listening on TCP 47800 and Tailscale-bound ports
8090/8091.

## Mac steps

Copy `halo-m8-web.tgz` to the Mac, then:

```sh
cd ~
tar -xzf halo-m8-web.tgz
cd halo-m8-web
python3 web_serve.py
```

Open:

<http://localhost:8000/?m8=ws://100.126.232.8:8091/game>

On the first visit:

1. Under **Game data**, click **Choose a maps folder…**.
2. Pick the `maps` folder from the user's own Halo extraction. If it is kept in the unpacked
   directory, that is `~/halo-m8-web/maps`. It is copied into browser-private storage for the
   localhost origin; it is not uploaded.
3. Under **Kevin (m8 companion)**, confirm the game URL. The mic URL should derive as
   `ws://100.126.232.8:8091/mic`.
4. Click **Turn microphone on**, grant permission, and wait for **Connected**.
5. Click **Play**.

The same instructions are included as `README-MAC.md` in the distribution.

## Known limitations

- The page uses `ScriptProcessorNode` for broad compatibility and simple 20 ms framing. Current
  Chromium logs its deprecation warning, but it remains functional. An AudioWorklet would remove
  the warning at the cost of another worker/module boundary.
- A plain `ws://` m8 address is appropriate for this `http://localhost` package. If the site is
  moved to public HTTPS, browsers require a corresponding secure `wss://` endpoint.
- By design, the newest native TCP or browser WebSocket game is active. Running both games at
  once makes their reconnect loops alternate ownership; normally only the game being played
  should be open.
- SwiftShader was intentionally used for verification and is much slower than the Mac's hardware
  WebGL2 renderer.
