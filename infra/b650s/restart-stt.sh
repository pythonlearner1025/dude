#!/usr/bin/env bash
# Restart the Parakeet STT server (e.g. after changing m8py/stt_server.py).
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pidfile="$ROOT/run/stt.pid"
if [[ -e "$pidfile" ]]; then
    pid="$(cut -d" " -f1 "$pidfile")"
    kill "$pid" 2>/dev/null
    for _ in $(seq 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid"
    rm -f "$pidfile"
fi
"$ROOT/scripts/start-stt.sh"
for _ in $(seq 60); do curl -sf http://127.0.0.1:8083/health >/dev/null && break; sleep 1; done
curl -s http://127.0.0.1:8083/health; echo
