#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_pid.sh"
mkdir -p "$ROOT/run" "$ROOT/logs"
pidfile="$ROOT/run/breeze.pid"
if pidfile_live "$pidfile"; then
    echo "Breeze is already running (PID $(pidfile_pid "$pidfile"))."
    exit 0
fi

fast=(--fast-backbone-decode --fast-depth-decoder --fast-codec)
if [[ "${BREEZE_MODE:-fast}" == "eager" ]]; then
    fast=()
fi
cd "$ROOT/breeze-tts"
nohup "${BREEZE_PYTHON:-$ROOT/breeze-tts/.venv/bin/python}" \
    -m breeze_infer.api "${BREEZE_MODEL:-$ROOT/models/breeze-tts-2}" \
    --host 127.0.0.1 --port "${BREEZE_PORT:-7860}" "${fast[@]}" \
    >>"$ROOT/logs/breeze.log" 2>&1 &
pid=$!
write_pidfile "$pid" "$pidfile"
echo "Started Breeze (PID $pid, log $ROOT/logs/breeze.log)."
