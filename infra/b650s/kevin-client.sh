#!/usr/bin/env bash
# Start Kevin's own Halo as co-op player 2 joining an invite, with no m8 link (the host's game keeps it).
# Set HALO_NET_ADDRESS only when a second copy runs on this machine (e.g. 127.0.0.6 beside a local host).
set -euo pipefail

invite=${1:-}
if [[ -z "$invite" ]]; then
	echo "usage: $0 <invite-link-or-64-hex-code>" >&2
	exit 2
fi

log_file=/home/minjune/m8work/logs/kevin-client.log
pid_file=/home/minjune/m8work/run/kevin-client.pid
if [[ -f "$pid_file" ]]; then
	old_pid=$(<"$pid_file")
	if [[ "$old_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
		echo "Kevin client is already running as PID $old_pid" >&2
		exit 1
	fi
fi

mkdir -p /home/minjune/m8work/logs /home/minjune/m8work/run
cd /home/minjune/m8work/halo/build/linux
setsid env \
	DISPLAY=:1 \
	XAUTHORITY=/home/minjune/m8work/run/Xauthority \
	XDG_RUNTIME_DIR=/run/user/1000 \
	SDL_VIDEODRIVER=x11 \
	SDL_AUDIODRIVER=pulseaudio \
	HALO_DISPLAY_MODE=windowed \
	HALO_WINDOW_SIZE=1280x720 \
	${HALO_NET_ADDRESS:+"HALO_NET_ADDRESS=$HALO_NET_ADDRESS"} \
	HALO_COOP_JOIN="$invite" \
	HALO_M8_COMPANION_ACTOR=false \
	HALO_M8_LINK=false \
	HALO_NET_EXTRA_ADDRESSES="${HALO_NET_EXTRA_ADDRESSES:-100.126.232.8}" \
	./halo >>"$log_file" 2>&1 </dev/null &
client_pid=$!
printf '%s\n' "$client_pid" >"$pid_file"
disown "$client_pid" 2>/dev/null || true
echo "Started Kevin client as PID $client_pid; log: $log_file"
