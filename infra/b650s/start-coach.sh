#!/usr/bin/env bash
# The coach: Claude Code with Opus works through m8py's tickets in the skill library
# (m8py/coach.py). Needs Claude Code signed in (`claude`, then /login) on this machine.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_pid.sh"
mkdir -p "$ROOT/run/tickets" "$ROOT/logs"
pidfile="$ROOT/run/coach.pid"
if pidfile_live "$pidfile"; then
    echo "The coach is already running (PID $(pidfile_pid "$pidfile"))."
    exit 0
fi
cd "$ROOT/dude"
PYTHONUNBUFFERED=1 nohup .venv/bin/python -m m8py.coach --library "$ROOT/kevin-skills" \
    --tickets "$ROOT/run/tickets" </dev/null >>"$ROOT/logs/coach.log" 2>&1 &
pid=$!
write_pidfile "$pid" "$pidfile"
echo "Started the coach (PID $pid, log $ROOT/logs/coach.log)."
