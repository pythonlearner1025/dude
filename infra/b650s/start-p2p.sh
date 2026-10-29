#!/usr/bin/env bash
# Open-P2P 600M on /tmp/uds.recap, taking its instruction from run/p2p-instruction.txt (~3.2 GB;
# 1200M does not fit beside the rest). Ready when the socket exists, after compiling (~1-2 min).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_pid.sh"
mkdir -p "$ROOT/run" "$ROOT/logs"
pidfile="$ROOT/run/p2p.pid"
if pidfile_live "$pidfile"; then
    echo "Open-P2P is already running (PID $(pidfile_pid "$pidfile"))."
    exit 0
fi
cd "$ROOT/open-p2p"
source env.sh
nohup .venv/bin/python "$ROOT/dude/tools/p2p/server.py" --model 600M \
    --instruction "$ROOT/run/p2p-instruction.txt" --log "$ROOT/logs/p2p-server.log" \
    </dev/null >>"$ROOT/logs/p2p-server.log" 2>&1 &
pid=$!
write_pidfile "$pid" "$pidfile"
echo "Started Open-P2P (PID $pid, log $ROOT/logs/p2p-server.log)."
