# Halo m8 streaming on minjune-650s

## Start and stop

Run as `minjune`; do not use `sudo` for these scripts.

```bash
/home/minjune/m8work/scripts/start-desktop.sh
/home/minjune/m8work/scripts/stop-desktop.sh
```

The start script creates Xorg display `:1` on the RTX 3090 Ti, selects the
physical monitor connected at kernel connector DP-4 (NVIDIA RandR name DP-0),
sets it to 1920x1080 at 60 Hz, starts Openbox, keeps a PulseAudio-compatible
session alive, creates the 48 kHz stereo `m8_null` sink and monitor, and starts
Sunshine. PIDs are in `/home/minjune/m8work/run/`; logs are in
`/home/minjune/m8work/logs/`.

Sunshine is intentionally run directly by the script. Its user systemd unit is
installed but not enabled. No display manager is enabled or used.

## Pair Moonlight on the Mac

1. Keep Tailscale connected on both machines.
2. In Moonlight, choose **Add PC** (or Add Host) and enter `100.126.232.8`.
3. Select the new host. Moonlight displays a PIN and Sunshine records a pending
   pairing request.
4. Open `https://100.126.232.8:47990` in a browser, accept the expected
   self-signed-certificate warning, log in with the values in
   `/home/minjune/m8work/notes/sunshine-creds.txt`, open **PIN**, select the
   pending Mac, enter Moonlight's PIN, and submit it.
5. Moonlight should then show **Desktop** and **Halo m8**. Halo will show its
   data prompt until the maps are installed.

An agent can submit the PIN without the browser. Authenticate with HTTP Basic
using the stored username/password. First `GET /api/pin`; its `pairings` array
contains the pending request's `id`. Then `POST /api/pin` with
`Content-Type: application/json` and this body:

```json
{"pairing_id":"<id from GET>","pin":"<Moonlight PIN>","name":"minjunes-macbook-pro-7"}
```

The complete API URL is `https://100.126.232.8:47990/api/pin`. Sunshine uses a
self-signed certificate, so command-line automation needs the equivalent of
`curl -k`; keep the credentials out of shell history. The authenticated GET was
tested and currently returns `{"pairings":[]}`, as expected before Moonlight
requests pairing.

## Recommended Moonlight settings

- Resolution: 1920x1080
- Frame rate: 60 FPS
- Codec: prefer HEVC; H.264 is also verified. The 3090 Ti does not support AV1
  encode, and Sunshine correctly falls back to H.264/HEVC.
- HDR: off (the X11 desktop is SDR)
- Bit rate: begin at 25 Mbps; 20-40 Mbps is a sensible adjustment range for
  1080p60 depending on the Mac's current network
- Audio: stereo, with host audio capture enabled
- Use Moonlight's normal frame pacing/V-sync option if tearing is visible

## Audio

The default sink is `m8_null`; the capture source is `m8_null.monitor`.
Sunshine's `audio_sink` is `m8_null`, which tells it to capture that sink's
monitor. OpenCE is launched with `SDL_AUDIODRIVER=pulseaudio`, so game audio and
m8 voice mixed by the game reach the stream.

Quick checks:

```bash
XDG_RUNTIME_DIR=/run/user/1000 pactl info
XDG_RUNTIME_DIR=/run/user/1000 pactl list short sinks
XDG_RUNTIME_DIR=/run/user/1000 pactl list short sources
```

The verification tone captured from `m8_null.monitor` measured -25.5 dB mean
and -20.5 dB peak; the recording is
`/home/minjune/m8work/logs/audio-monitor.wav`.

## Network and ports

Sunshine is bound only to the host's Tailscale address `100.126.232.8`.
Before a stream, TCP 47984, 47989, 47990, and 48010 listen there. Sunshine
creates its UDP media sockets (47998 video, 47999 control, 48000 audio) when a
Moonlight session begins, so those three do not appear in `ss` before pairing.

To inspect:

```bash
sudo ss -lntup | grep -E '47984|47989|47990|48010|47998|47999|48000'
```

To check whether Tailscale is direct or relayed:

```bash
tailscale ping minjunes-macbook-pro-7
```

On 2026-10-27 the check began via `DERP(sfo)` (11-111 ms), then upgraded to a
direct path via `135.180.43.224:44291` at 8 ms. That final direct line is the
desired state; it can change as either network changes.

## GPU and diagnostics

With Xorg and idle Sunshine running, `nvidia-smi` reported 329 MiB / 23028 MiB:
15 MiB attributed to Xorg and 262 MiB to Sunshine. Sunshine's encoder probe
found both `h264_nvenc` and `hevc_nvenc`.

Useful files:

- Sunshine: `/home/minjune/m8work/logs/sunshine.log`
- Xorg wrapper output: `/home/minjune/m8work/logs/xorg.log`
- Full Xorg log: `/var/log/Xorg.1.log`
- OpenCE first start: `/home/minjune/m8work/logs/halo-first-start.log`
- Screenshot: `/home/minjune/m8work/logs/halo-first-start.png`
- GL evidence: `/home/minjune/m8work/logs/glxinfo.txt`

## System-level changes made

- Refreshed apt package indexes. The pre-existing Spotify repository had a
  missing signing key, so apt retained its previous Spotify index; this did not
  affect these installs.
- Installed Sunshine `2026.914.233613-1+ubuntu22.04` from the stable LizardByte
  GitHub release asset after verifying SHA-256
  `c7645396027b0601a09d49de89674b80b3c9ac7a3dffe0d52703738dab072f1c`.
- Directly requested packages: `sunshine`, `openbox`, and `imagemagick`.
  Dependencies installed in the same transaction: `gsfonts`,
  `imagemagick-6-common`, `imagemagick-6.q16`, `libfftw3-double3`, `libid3tag0`,
  `libilmbase25`, `libimlib2`, `libjxr-tools`, `libjxr0`, `liblqr-1-0`,
  `libmagickcore-6.q16-6`, `libmagickcore-6.q16-6-extra`,
  `libmagickwand-6.q16-6`, `libnetpbm10`, `libobrender32v5`, `libobt2v5`,
  `libopenexr25`, `miniupnpc`, `netpbm`, `obconf`, and `scrot`.
- Sunshine's package installed `/lib/udev/rules.d/60-sunshine.rules`,
  `/usr/lib/modules-load.d/60-sunshine.conf`, and its user service file; its
  post-install loaded `uhid`, reloaded udev rules, and set
  `cap_sys_admin,cap_sys_nice+p` on `/usr/bin/sunshine`.
- Replaced `/etc/X11/Xwrapper.config` with the dedicated documented policy
  `allowed_users=anybody` and `needs_root_rights=yes`, needed to start NVIDIA
  Xorg from this non-console session.
- Added `/etc/X11/m8-xorg.conf`. It selects only PCI `1:0:0` (the NVIDIA GPU)
  for this explicitly named config; normal Xorg startup does not load it.
- No display manager was installed or enabled, no system Sunshine service was
  enabled, the default target remains `graphical.target`, and the machine was
  not rebooted.

The first OpenCE launch created its normal defaults file at
`/home/minjune/m8work/halo/build/linux/config.toml`. No game source was changed.
