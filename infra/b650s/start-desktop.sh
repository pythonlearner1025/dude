#!/usr/bin/env bash
set -euo pipefail

base=/home/minjune/m8work
run_dir="$base/run"
log_dir="$base/logs"
display=:1
runtime_dir=/run/user/1000
xauthority="$run_dir/Xauthority"

if [[ $(id -u) -ne 1000 || $(id -un) != minjune ]]; then
    echo "Run this script as user minjune." >&2
    exit 1
fi

mkdir -p "$run_dir" "$log_dir"
export XDG_RUNTIME_DIR="$runtime_dir"

pid_running() {
    [[ -f "$1" ]] && kill -0 "$(<"$1")" 2>/dev/null
}

if pid_running "$run_dir/xorg.pid"; then
    echo "The m8 Xorg session is already running." >&2
    exit 0
fi

# Keep one PulseAudio SDL-compatible server alive for the lifetime of the
# streaming desktop. Stop socket activation first to avoid two daemons racing
# for /run/user/1000/pulse/native. PipeWire remains user-service managed.
if pid_running "$run_dir/pulseaudio.pid" && pulseaudio --check 2>/dev/null; then
    audio_pid=$(<"$run_dir/pulseaudio.pid")
else
    systemctl --user stop pulseaudio.socket pulseaudio.service 2>/dev/null || true
    systemctl --user reset-failed pulseaudio.socket pulseaudio.service 2>/dev/null || true
    pulseaudio --daemonize=yes --exit-idle-time=-1 --log-target="file:$log_dir/pulseaudio.log"
    for _ in {1..30}; do
        pulseaudio --check 2>/dev/null && break
        sleep 0.1
    done
    audio_pid=$(<"$runtime_dir/pulse/pid")
    printf '%s\n' "$audio_pid" > "$run_dir/pulseaudio.pid"
fi

if pactl list short sinks | awk '{print $2}' | grep -qx m8_null; then
    pactl set-default-sink m8_null
else
    module_id=$(pactl load-module module-null-sink sink_name=m8_null rate=48000 channels=2 \
        sink_properties=device.description=M8_Stream_Audio)
    printf '%s\n' "$module_id" > "$run_dir/audio-null-module"
    pactl set-default-sink m8_null
fi

xauth -f "$xauthority" remove "$display" 2>/dev/null || true
xauth -f "$xauthority" add "$display" . "$(mcookie)"
nohup Xorg "$display" -config m8-xorg.conf \
    -auth "$xauthority" -nolisten tcp -noreset > "$log_dir/xorg.log" 2>&1 &
printf '%s\n' "$!" > "$run_dir/xorg.pid"

export DISPLAY="$display"
export XAUTHORITY="$xauthority"
for _ in {1..50}; do
    if xdpyinfo >/dev/null 2>&1; then
        break
    fi
    if ! pid_running "$run_dir/xorg.pid"; then
        echo "Xorg exited; see $log_dir/xorg.log" >&2
        exit 1
    fi
    sleep 0.2
done
xdpyinfo >/dev/null

# Kernel connector DP-4 is NVIDIA RandR output DP-0. Its native mode is 4K,
# so use the requested 1080p60 stream mode.
xrandr --output DP-0 --primary --mode 1920x1080 --rate 60
xset s off

nohup setsid openbox > "$log_dir/openbox.log" 2>&1 &
printf '%s\n' "$!" > "$run_dir/openbox.pid"

nohup setsid sunshine "$HOME/.config/sunshine/sunshine.conf" \
    > "$log_dir/sunshine.log" 2>&1 &
printf '%s\n' "$!" > "$run_dir/sunshine.pid"

for _ in {1..50}; do
    if ss -ltnH '( sport = :47990 )' | grep -q .; then
        break
    fi
    if ! pid_running "$run_dir/sunshine.pid"; then
        echo "Sunshine exited; see $log_dir/sunshine.log" >&2
        exit 1
    fi
    sleep 0.2
done

sleep 1
if ! pid_running "$run_dir/sunshine.pid"; then
    echo "Sunshine exited after initialization; see $log_dir/sunshine.log" >&2
    exit 1
fi
if ! pid_running "$run_dir/openbox.pid"; then
    echo "Openbox exited after initialization; see $log_dir/openbox.log" >&2
    exit 1
fi

echo "m8 desktop is running on $display at 1920x1080; Sunshine PID $(<"$run_dir/sunshine.pid")."
