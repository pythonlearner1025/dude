#!/usr/bin/env bash
# Starts m8py (the companion brain) with configs/b650s.toml; the game connects to it on :47800.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_pid.sh"
mkdir -p "$ROOT/run" "$ROOT/logs"
pidfile="$ROOT/run/m8py.pid"
if pidfile_live "$pidfile"; then
    echo "m8py is already running (PID $(pidfile_pid "$pidfile"))."
    exit 0
fi
cd "${DUDE_DIR:-$ROOT/dude}"
PYTHONUNBUFFERED=1 nohup .venv/bin/python -m m8py run "${M8PY_CONFIG:-configs/b650s.toml}" \
    </dev/null >>"$ROOT/logs/m8py.log" 2>&1 &
pid=$!
write_pidfile "$pid" "$pidfile"
echo "Started m8py (PID $pid, log $ROOT/logs/m8py.log)."
