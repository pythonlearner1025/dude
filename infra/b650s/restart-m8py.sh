#!/usr/bin/env bash
# Restart m8py on the current checkout. It runs under a systemd user unit so it outlives the ssh
# session that started it; the unit ends when m8py exits. M8PY_CONFIG picks the config
# (configs/b650s-coop.toml for co-op mode).
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pidfile="$ROOT/run/m8py.pid"
if [[ -e "$pidfile" ]]; then
    pid="$(cut -d" " -f1 "$pidfile")"
    kill -INT "$pid" 2>/dev/null
    for _ in $(seq 16); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid"
    rm -f "$pidfile"
fi
for unit in $(systemctl --user list-units --no-legend "m8py*" | awk '{print $1}'); do
    systemctl --user stop "$unit"
done
lines="$(wc -l < "$ROOT/logs/m8py.log")"
systemd-run --user --unit="m8py-$(date +%H%M%S)" --collect \
    --setenv=M8PY_CONFIG="${M8PY_CONFIG:-configs/b650s.toml}" bash -c \
    "$ROOT/scripts/start-m8py.sh; while kill -0 \$(cut -d' ' -f1 $pidfile) 2>/dev/null; do sleep 5; done" \
    >/dev/null
for _ in $(seq 60); do
    tail -n +"$lines" "$ROOT/logs/m8py.log" | grep -q "Ready!" && break
    sleep 1
done
tail -n +"$lines" "$ROOT/logs/m8py.log" | grep -E "Ready|Error" | tail -2
