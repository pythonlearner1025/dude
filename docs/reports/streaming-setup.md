# Sunshine / Halo m8 streaming report

## Result

The manual Xorg desktop and Sunshine are running and ready for Moonlight
pairing at `100.126.232.8`. The session uses the RTX 3090 Ti, physical kernel
connector DP-4 (NVIDIA RandR name DP-0), 1920x1080 at 60 Hz, Openbox, the
`m8_null` PulseAudio sink, X11 capture, and NVIDIA NVENC. No display manager or
system Sunshine service was enabled, the boot target was not changed, and no
reboot was performed.

Current tracked processes:

| Component | PID | State |
|---|---:|---|
| Xorg `:1` | 2144454 | running, detached session |
| Openbox | 2144466 | running, detached session |
| Sunshine | 2144467 | running, detached session |
| PulseAudio | 2144440 | running, persistent for this desktop |

The PIDs remain authoritative in `/home/minjune/m8work/run/*.pid` if they later
change.

## Installed and changed

- Installed stable LizardByte Sunshine
  `2026.914.233613-1+ubuntu22.04` from the release's Ubuntu 22.04 amd64 `.deb`.
  Verified release SHA-256:
  `c7645396027b0601a09d49de89674b80b3c9ac7a3dffe0d52703738dab072f1c`.
- Installed Openbox and ImageMagick plus the dependency packages enumerated in
  `/home/minjune/m8work/notes/streaming.md`.
- Sunshine installed its udev/modules-load files and user unit, loaded `uhid`,
  and set `cap_sys_admin,cap_sys_nice+p` on `/usr/bin/sunshine`. The user unit
  is not enabled.
- `/etc/X11/Xwrapper.config`: `allowed_users=anybody` and
  `needs_root_rights=yes` for manual NVIDIA Xorg from a non-console login.
- `/etc/X11/m8-xorg.conf`: dedicated RTX 3090 Ti config, loaded only by the m8
  start script.
- No GDM/LightDM enablement and no default-target change (`graphical.target`
  remains the default).

User-owned files:

- `/home/minjune/m8work/scripts/start-desktop.sh`
- `/home/minjune/m8work/scripts/stop-desktop.sh`
- `/home/minjune/m8work/scripts/run-halo.sh`
- `/home/minjune/.config/sunshine/sunshine.conf`
- `/home/minjune/.config/sunshine/apps.json`
- `/home/minjune/m8work/notes/sunshine-creds.txt` (mode 0600)
- `/home/minjune/m8work/notes/streaming.md`

## Usage

Run as `minjune`:

```bash
/home/minjune/m8work/scripts/start-desktop.sh
/home/minjune/m8work/scripts/stop-desktop.sh
```

Sunshine's authenticated apps API returned:

```text
Desktop
Halo m8
```

`Halo m8` invokes `run-halo.sh`, which changes to the binary directory, forces
SDL X11 plus PulseAudio, and requests borderless 1920x1080. Credentials and the
complete browser/API pairing procedure are in `notes/streaming.md`.

## Verification evidence

### Display and OpenGL

```text
DP-0 connected primary 1920x1080+0+0
1920x1080  74.97  60.00*  59.94
direct rendering: Yes
OpenGL vendor string: NVIDIA Corporation
OpenGL renderer string: NVIDIA GeForce RTX 3090 Ti/PCIe/SSE2
OpenGL core profile version string: 4.6.0 NVIDIA 580.95.05
OpenGL version string: 4.6.0 NVIDIA 580.95.05
```

The installed i386 path resolves to NVIDIA:

```text
libnvidia-gl-580:i386  580.95.05-0ubuntu1
libGLX_nvidia.so.0 (libc6) => /lib/i386-linux-gnu/libGLX_nvidia.so.0
libGL.so.1 (libc6) => /lib/i386-linux-gnu/libGL.so.1
```

### Sunshine and NVENC

Key `sunshine.log` lines:

```text
Screencasting with X11
Streaming display: DP-0 with res 1920x1080 offset by 0x0
Found H.264 encoder: h264_nvenc [nvenc]
Found HEVC encoder: hevc_nvenc [nvenc]
Configuration UI available at [https://100.126.232.8:47990]
```

The RTX 3090 Ti correctly rejected AV1 during capability probing; H.264 and
HEVC are the usable hardware encoders.

Before a stream, these listeners are bound only to the Tailscale address:

```text
100.126.232.8:47984/tcp
100.126.232.8:47989/tcp
100.126.232.8:47990/tcp
100.126.232.8:48010/tcp
```

Sunshine creates UDP 47998 (video), 47999 (control), and 48000 (audio) when an
actual Moonlight stream begins; they are not bound before pairing. Their
pre-stream absence is expected, but live UDP transport remains the one check
that necessarily waits for the user's Moonlight connection.

### Audio

```text
Server Name: pulseaudio
Default Sink: m8_null
Default Source: m8_null.monitor
m8_null          s16le 2ch 48000Hz
m8_null.monitor  s16le 2ch 48000Hz
```

A 1 kHz tone played with `paplay` into `m8_null` was recorded from
`m8_null.monitor`:

```text
Duration: 00:00:01.06
mean_volume: -25.5 dB
max_volume: -20.5 dB
```

This verifies the exact loopback source Sunshine will capture.

### OpenCE first start

The 32-bit binary opened an X window titled `Halo`. Its prompt reads:

```text
Halo's game data (its maps folder) was not found.
```

The full 1920x1080 screenshot is
`/home/minjune/m8work/logs/halo-first-start.png` (SHA-256
`c64645582fd24f9c7d693bb4103cf9877a3a77e7c6307c7f53bfd2ab2b1fae41`).
The test process and its Zenity child were closed; no Halo process was left
running. First start wrote OpenCE's normal `build/linux/config.toml` defaults.

### GPU memory

With Xorg and idle Sunshine running:

```text
329 MiB / 23028 MiB total GPU memory
Xorg:     15 MiB
Sunshine: 262 MiB
```

### Tailscale path to the Mac

`tailscale ping minjunes-macbook-pro-7` initially used `DERP(sfo)` at 11-111
ms, then upgraded during the same run to the direct endpoint
`135.180.43.224:44291` at 8 ms. The latest result was therefore **direct**, not
DERP-relayed.

## Remaining user steps

1. On the Mac, keep Tailscale connected and add host `100.126.232.8` in
   Moonlight.
2. Submit Moonlight's PIN in the Sunshine web UI at
   `https://100.126.232.8:47990`; credentials are in the mode-0600 credentials
   file. The `/api/pin` automation procedure is in `notes/streaming.md`.
3. Start **Desktop** to confirm input/audio and the live UDP listeners, or
   **Halo m8** after installing the legally obtained Halo maps.
4. Begin with 1080p60, HEVC, HDR off, stereo audio, and 25 Mbps.

The desktop and Sunshine are intentionally left running for pairing.
