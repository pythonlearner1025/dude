#!/usr/bin/env bash
set -euo pipefail

export DISPLAY=${DISPLAY:-:1}
export XAUTHORITY=${XAUTHORITY:-/home/minjune/m8work/run/Xauthority}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}
export SDL_VIDEODRIVER=x11
export SDL_AUDIODRIVER=pulseaudio
export HALO_DISPLAY_MODE=borderless
export HALO_RESOLUTION=1920x1080

cd /home/minjune/m8work/halo/build/linux
exec ./halo
