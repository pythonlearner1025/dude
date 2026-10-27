#!/usr/bin/env bash
set -euo pipefail

base=/home/minjune/m8work
run_dir="$base/run"

if [[ $(id -u) -ne 1000 || $(id -un) != minjune ]]; then
    echo "Run this script as user minjune." >&2
    exit 1
fi

stop_pid_file() {
    local pid_file=$1
    local label=$2
    local pid
    [[ -f "$pid_file" ]] || return 0
    pid=$(<"$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        for _ in {1..30}; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.1
        done
    fi
    : > "$pid_file"
    echo "Stopped $label."
}

stop_pid_file "$run_dir/sunshine.pid" Sunshine
stop_pid_file "$run_dir/openbox.pid" Openbox
stop_pid_file "$run_dir/xorg.pid" Xorg

export XDG_RUNTIME_DIR=/run/user/1000
if [[ -s "$run_dir/audio-null-module" ]] && pulseaudio --check 2>/dev/null; then
    pactl unload-module "$(<"$run_dir/audio-null-module")" 2>/dev/null || true
    : > "$run_dir/audio-null-module"
fi
stop_pid_file "$run_dir/pulseaudio.pid" PulseAudio
systemctl --user reset-failed pulseaudio.socket pulseaudio.service 2>/dev/null || true
systemctl --user start pulseaudio.socket

echo "m8 desktop is stopped."
