#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_pid.sh"
for name in m8py p2p-client kevin-client p2p kev chat chat-qwen breeze stt; do
    pidfile="$ROOT/run/$name.pid"
    [[ -e "$pidfile" ]] || continue
    pid="$(pidfile_pid "$pidfile" 2>/dev/null || true)"
    if pidfile_live "$pidfile"; then
        kill "$pid"
        echo "Stopped $name (PID $pid)."
    else
        echo "$name PID record was stale; no process was signalled."
    fi
    rm -f "$pidfile"
done
