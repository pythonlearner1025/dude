#!/usr/bin/env bash
# The coach: Claude Code with Opus watches m8py's session trace and keeps the skill library up
# (m8py/coach.py), about once a minute while someone plays. Packets and results go to
# run/observations/<session>/<n>/. It signs in with the long-lived token from
# `claude setup-token`, kept in notes/claude-coach.env (CLAUDE_CODE_OAUTH_TOKEN=..., mode 600).
# COACH_MODEL and COACH_EFFORT choose the model (default Opus 5.5) and its effort (medium).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_pid.sh"
mkdir -p "$ROOT/run/observations" "$ROOT/logs"
pidfile="$ROOT/run/coach.pid"
if pidfile_live "$pidfile"; then
    echo "The coach is already running (PID $(pidfile_pid "$pidfile"))."
    exit 0
fi
if [[ -f "$ROOT/notes/claude-coach.env" ]]; then
    set -a
    source "$ROOT/notes/claude-coach.env"
    set +a
fi
claude="$HOME/.npm-global/bin/claude"  # current Claude Code; /usr/local's is old
[[ -x "$claude" ]] || claude=claude
cd "$ROOT/dude"
PYTHONUNBUFFERED=1 setsid nohup .venv/bin/python -m m8py.coach --library "$ROOT/kevin-skills" \
    --logs "$ROOT/dude/logs" --out "$ROOT/run/observations" --claude "$claude" \
    --model "${COACH_MODEL:-claude-opus-5-5}" --effort "${COACH_EFFORT:-medium}" \
    </dev/null >>"$ROOT/logs/coach.log" 2>&1 &
pid=$!
write_pidfile "$pid" "$pidfile"
echo "Started the coach (PID $pid, log $ROOT/logs/coach.log)."
