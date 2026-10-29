# Kevin co-op client

Completed on 2026-10-28 against OpenCE branch `m8-web`.

## Engine change

Halo commit: `005273c324f97df3c43e64ae3b073717c3bfedd2` (`Add automatic internet co-op startup`).

New settings:

- `HALO_COOP_HOST=<campaign level>` hosts private internet co-op without menus.
- `HALO_COOP_JOIN=<invite or 64-hex code>` joins without menus with a red player profile named Kevin, creating it when absent.
- `HALO_COOP_WAIT=<seconds>` starts a host alone after the timeout; `0` waits for player 2.
- `HALO_COOP_INVITE_FILE=<path>` writes the invite link. The web build also sends `{"type":"invite","link":"..."}` over a connected m8 link.
- `HALO_M8_COMPANION_ACTOR=false` disables the AI Kevin actor without removing the m8 link. Network games disable the actor regardless.
- `HALO_NET_EXTRA_ADDRESSES=<IPv4[,IPv4...]>` adds VPN/directly reachable ICE candidates.

The generic web `?set=NAME=value` parameter exposes all of these settings, for example `?set=HALO_COOP_HOST=a30`.

## Commands

For two copies on b650s, bind the game's fixed ports to separate loopback addresses:

```bash
cd /home/minjune/m8work/halo/build/linux
DISPLAY=:1 XAUTHORITY=/home/minjune/m8work/run/Xauthority \
SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=pulseaudio \
HALO_DISPLAY_MODE=windowed HALO_WINDOW_SIZE=960x540 \
HALO_NET_ADDRESS=127.0.0.2 HALO_COOP_HOST=a30 HALO_COOP_WAIT=0 \
HALO_COOP_INVITE_FILE=/home/minjune/m8work/coop-test/invite.txt ./halo
```

```bash
cd /home/minjune/m8work/halo/build/linux
DISPLAY=:1 XAUTHORITY=/home/minjune/m8work/run/Xauthority \
SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=pulseaudio \
HALO_DISPLAY_MODE=windowed HALO_WINDOW_SIZE=960x540 \
HALO_NET_ADDRESS=127.0.0.3 \
HALO_COOP_JOIN="$(sed -n '1p' /home/minjune/m8work/coop-test/invite.txt)" ./halo
```

For normal Kevin-client use:

```bash
~/m8work/scripts/kevin-client.sh 'halo://join/<64-hex-code>'
```

It starts on display `:1` at 1280x720, appends to `/home/minjune/m8work/logs/kevin-client.log`, and writes `/home/minjune/m8work/run/kevin-client.pid`.

## Native test evidence

Both instances connected through the invite and entered `levels\\a30\\a30`. The host log names player 0 `Player`, player 1 `Kevin`, and says `Kevin's AI companion actor is off in a network game`.

- Host screenshot: `/home/minjune/m8work/coop-test/host.png`
- Client before movement: `/home/minjune/m8work/coop-test/client-before.png`
- Client after movement: `/home/minjune/m8work/coop-test/client-after.png`
- Host log: `/home/minjune/m8work/coop-test/host.log`
- Client log: `/home/minjune/m8work/coop-test/client.log`

Holding W in the client window for two seconds with `xdotool` moved player 1 from `(31.501, -102.511, 58.761)` to `(30.953, -98.058, 58.380)`. The intermediate log reports throttle `1.00`.

## WebRTC and Tailscale

The native WebRTC description uses `p2p_local_candidates()`. Without an override this machine advertises its default-route LAN address (`192.168.5.25`), then any UPnP and STUN-mapped public addresses (observed `76.191.157.41`); it uses loopback only if it has no other candidate. It does not enumerate every interface, so `tailscale0` (`100.126.232.8`) was not advertised by default.

With `HALO_NET_EXTRA_ADDRESSES=100.126.232.8`, the native build logged `Internet play: advertising extra address 100.126.232.8:<tunnel-port>`. Evidence is in `/home/minjune/m8work/coop-test/tailscale-candidate.log`. The Kevin launcher sets this address by default and allows the environment to override it.

## Builds and checks

- Baseline and final native builds: `ninja linux` passed; the baseline and final binaries both started on `:1` with NVIDIA OpenGL 4.5 on the RTX 3090 Ti.
- Web build: `ninja web` passed; output is `/home/minjune/m8work/halo/build/web/site/`.
- Focused tests: `24 passed, 4 skipped` for `tools/test_web_build.py` and `tools/test_linux_port.py`.
- The Mac browser test was intentionally not attempted. The built web package still needs deployment to the Mac.

The m8 model stack was not stopped during this work, so it did not require a restart. Final verification returned `{"status":"ok"}` from `localhost:8081/health`; `/home/minjune/m8work/logs/m8py.log` contains the expected `Ready!` line and the m8py process remains running.

## Fixes (2026-10-28)

Halo commits `0306e3d6` and `db6032a2` add `HALO_M8_LINK` and keep the host's
full companion update path running in network co-op while skipping only the AI
actor. The host now describes the remote real player 2 as Kevin (position,
health, shields, weapon, observed activity, and death/kill events) and offers no
actor actions. The Kevin client keeps `HALO_M8_LINK=false`; its launcher now
defaults `HALO_NET_ADDRESS` to `127.0.0.6`.

A short native paired run is in
`/home/minjune/m8work/coop-test/m8-coop-QQlKNZ/`. The host and client both name
player 0 `Player` and player 1 `Kevin`; the host later reports both live units,
and the client reports local player 1. Both report the AI companion actor off.
Final `ninja linux` and `ninja web` builds passed.

The requested live m8py trace check could not complete without restarting
m8py, which was forbidden. Before and throughout verification, PID 2323931 was
CPU-bound at 98%; `m8py.log` stopped changing at 21:03:34 and the newest
`trace.jsonl` stopped changing at 18:34:17. The game's host TCP connections did
reach `127.0.0.1:47800` and sent roughly 98--123 KB each, but m8py left roughly
128 KB unread on each server socket and did not run its accept callback (so it
logged no new `[game] connected` line). This rules out the internet-play socket
layer and `HALO_NET_ADDRESS` as the cause of the observed connection failure;
the current remaining blocker is the already-stalled m8py event loop.
