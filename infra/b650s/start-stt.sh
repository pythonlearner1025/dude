#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_pid.sh"
DUDE="${DUDE_DIR:-$ROOT/dude}"
mkdir -p "$ROOT/run" "$ROOT/logs"
pidfile="$ROOT/run/stt.pid"
if pidfile_live "$pidfile"; then
    echo "STT is already running (PID $(pidfile_pid "$pidfile"))."
    exit 0
fi

python="${STT_PYTHON:-$DUDE/.venv/bin/python}"
if [[ ! -x "$python" ]]; then python="${STT_PYTHON:-python3}"; fi
cd "$DUDE"
nohup "$python" -m m8py.stt_server \
    "${PARAKEET_MODEL:-$ROOT/models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8}" \
    "${STT_PORT:-8083}" \
    >>"$ROOT/logs/stt.log" 2>&1 &
pid=$!
write_pidfile "$pid" "$pidfile"
echo "Started STT (PID $pid, log $ROOT/logs/stt.log)."
