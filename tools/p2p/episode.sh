#!/usr/bin/env bash
set -euo pipefail

name=${1:?usage: episode.sh NAME INSTRUCTION}
instruction=${2-}
duration=${P2P_DURATION:-60}
base=/home/minjune/m8work
out=$base/p2p-test
invite=$out/$name-invite.txt
host_log=$out/$name-host.log
client_log=$out/$name-client.log
action_log=$out/$name-actions.jsonl
gpu_log=$out/$name-gpu.csv
mkdir -p "$out" "$out/$name-keyframes"
rm -f "$invite" "$host_log" "$client_log" "$action_log" "$gpu_log"
printf '%s\n' "$instruction" >$base/run/p2p-instruction.txt

host_pid= client_pid= p2p_pid= ffmpeg_pid= gpu_pid= focus_pid=
cleanup() {
    for pid in "$p2p_pid" "$ffmpeg_pid" "$gpu_pid" "$focus_pid" "$client_pid" "$host_pid"; do
        if [[ $pid =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    for pid in "$p2p_pid" "$ffmpeg_pid" "$gpu_pid" "$focus_pid" "$client_pid" "$host_pid"; do
        if [[ $pid =~ ^[0-9]+$ ]]; then wait "$pid" 2>/dev/null || true; fi
    done
}
trap cleanup EXIT INT TERM

cd $base/halo/build/linux
env DISPLAY=:1 XAUTHORITY=$base/run/Xauthority XDG_RUNTIME_DIR=/run/user/1000 \
    SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=pulseaudio HALO_NO_AUDIO=1 \
    HALO_HIDDEN_WINDOW=true HALO_NET_ADDRESS=127.0.0.2 \
    HALO_COOP_HOST=a30 HALO_COOP_WAIT=0 HALO_COOP_INVITE_FILE="$invite" \
    HALO_MOUSE_SENSITIVITY=0.61091 ./halo >"$host_log" 2>&1 &
host_pid=$!

for _ in $(seq 1 300); do
    [[ -s $invite ]] && break
    kill -0 "$host_pid"
    sleep .1
done
[[ -s $invite ]] || { echo "host did not write invite" >&2; exit 1; }

kevin_log=$base/logs/kevin-client.log
start_byte=$(( $(stat -c %s "$kevin_log" 2>/dev/null || echo 0) + 1 ))
env HALO_NET_ADDRESS=127.0.0.3 HALO_MOUSE_SENSITIVITY=0.61091 HALO_NO_AUDIO=1 \
    $base/dude/scripts-staging/kevin-client.sh "$(head -n 1 "$invite")"
client_pid=$(head -n 1 $base/run/kevin-client.pid)
[[ $client_pid =~ ^[0-9]+$ ]] || { echo "bad Kevin PID" >&2; exit 1; }

window=
for _ in $(seq 1 600); do
    window=$(DISPLAY=:1 XAUTHORITY=$base/run/Xauthority xdotool search --onlyvisible --pid "$client_pid" 2>/dev/null | tail -n 1 || true)
    [[ $window =~ ^[0-9]+$ ]] && break
    kill -0 "$client_pid"
    sleep .1
done
[[ $window =~ ^[0-9]+$ ]] || { echo "Kevin window not found" >&2; exit 1; }
DISPLAY=:1 XAUTHORITY=$base/run/Xauthority xdotool windowactivate --sync "$window"
(
    while kill -0 "$client_pid" 2>/dev/null; do
        active=$(DISPLAY=:1 XAUTHORITY=$base/run/Xauthority xdotool getactivewindow 2>/dev/null || true)
        active_owner=$(DISPLAY=:1 XAUTHORITY=$base/run/Xauthority xdotool getwindowpid "$active" 2>/dev/null || true)
        if [[ $active_owner != "$client_pid" ]]; then
            DISPLAY=:1 XAUTHORITY=$base/run/Xauthority xdotool windowactivate --sync "$window" 2>/dev/null || true
        fi
        sleep .25
    done
) &
focus_pid=$!

# Begin the take after Kevin has spawned, or after a bounded 30-second wait.
for _ in $(seq 1 300); do
    if tail -c +"$start_byte" "$kevin_log" 2>/dev/null | rg -q 'player 1: \('; then break; fi
    kill -0 "$client_pid"
    sleep .1
done

if [[ $name == empty ]]; then
    active=$(DISPLAY=:1 XAUTHORITY=$base/run/Xauthority xdotool getactivewindow)
    active_pid=$(DISPLAY=:1 XAUTHORITY=$base/run/Xauthority xdotool getwindowpid "$active")
    [[ $active_pid == "$client_pid" ]] || { echo "refusing calibration without Kevin focused" >&2; exit 1; }
    before=$(tail -c +"$start_byte" "$kevin_log" | sed -n 's/.*player 1: ([^)]*)[^|]* a\([-0-9]*\)\/.*/\1/p' | tail -n 1)
    $base/open-p2p/.venv/bin/python - <<'PY'
import time
from evdev import UInput, ecodes as e
caps = {e.EV_KEY: [e.KEY_W, e.BTN_LEFT], e.EV_REL: [e.REL_X, e.REL_Y]}
with UInput(caps, name="Open-P2P Kevin keyboard mouse") as device:
    time.sleep(1)  # let SDL hotplug the uinput device
    device.write(e.EV_REL, e.REL_X, 128)
    device.syn()
    time.sleep(2)
PY
    after=$(tail -c +"$start_byte" "$kevin_log" | sed -n 's/.*player 1: ([^)]*)[^|]* a\([-0-9]*\)\/.*/\1/p' | tail -n 1)
    $base/open-p2p/.venv/bin/python - <<'PY'
import time
from evdev import UInput, ecodes as e
caps = {e.EV_KEY: [e.KEY_W, e.BTN_LEFT], e.EV_REL: [e.REL_X, e.REL_Y]}
with UInput(caps, name="Open-P2P Kevin keyboard mouse") as device:
    time.sleep(1)
    device.write(e.EV_REL, e.REL_X, -128)
    device.syn()
    time.sleep(1)
PY
    printf 'model_delta_counts=100\ninjected_uinput_counts=128\nmouse_scale=1.28\nsensitivity=0.61091\nyaw_before_deg=%s\nyaw_after_deg=%s\n' \
        "$before" "$after" >"$out/calibration.txt"
fi

geometry=$(DISPLAY=:1 XAUTHORITY=$base/run/Xauthority xdotool getwindowgeometry --shell "$window")
x=$(awk -F= '$1=="X" {print $2}' <<<"$geometry")
y=$(awk -F= '$1=="Y" {print $2}' <<<"$geometry")
width=$(awk -F= '$1=="WIDTH" {print $2}' <<<"$geometry")
height=$(awk -F= '$1=="HEIGHT" {print $2}' <<<"$geometry")

printf 'timestamp_ms,memory_used_mib,utilization_pct\n' >"$gpu_log"
(
    end=$((SECONDS + duration + 1))
    while (( SECONDS < end )); do
        sample=$(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits)
        printf '%s,%s\n' "$(( $(date +%s%N) / 1000000 ))" "${sample// /}" >>"$gpu_log"
        sleep 1
    done
) &
gpu_pid=$!

DISPLAY=:1 XAUTHORITY=$base/run/Xauthority /usr/bin/ffmpeg -hide_banner -loglevel error -y \
    -f x11grab -framerate 15 -video_size "${width}x${height}" -i ":1.0+$x,$y" \
    -t "$duration" -c:v libx264 -preset veryfast -crf 28 -pix_fmt yuv420p "$out/$name.mp4" &
ffmpeg_pid=$!

DISPLAY=:1 XAUTHORITY=$base/run/Xauthority \
    $base/open-p2p/.venv/bin/python $base/dude/tools/p2p/client.py \
    --window-pid "$client_pid" --window-title '' --duration "$duration" --mouse-scale 1.28 \
    --log "$action_log" &
p2p_pid=$!
wait "$p2p_pid"
p2p_pid=
wait "$ffmpeg_pid" || true
ffmpeg_pid=
wait "$gpu_pid" || true
gpu_pid=
kill "$focus_pid" 2>/dev/null || true
wait "$focus_pid" 2>/dev/null || true
focus_pid=
tail -c +"$start_byte" "$kevin_log" >"$client_log"

/usr/bin/ffmpeg -hide_banner -loglevel error -y -i "$out/$name.mp4" \
    -vf 'select=eq(n\,150)+eq(n\,450)+eq(n\,750)' -vsync 0 "$out/$name-keyframes/frame-%02d.png"
