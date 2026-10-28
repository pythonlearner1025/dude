#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_pid.sh"
mkdir -p "$ROOT/run" "$ROOT/logs"
pidfile="$ROOT/run/kev.pid"
if pidfile_live "$pidfile"; then
    echo "Kev is already running (PID $(pidfile_pid "$pidfile"))."
    exit 0
fi

quant="${KEV_QUANT:-Q8_0}"
case "$quant" in
    Q8_0|q8_0) model="$ROOT/models/kev-4b/Kev-4B-Q8_0.gguf" ;;
    Q4_K_M|q4_k_m) model="$ROOT/models/kev-4b/Kev-4B-Q4_K_M.gguf" ;;
    *) echo "KEV_QUANT must be Q8_0 or Q4_K_M" >&2; exit 2 ;;
esac

# systemone needs a whole question in one micro-batch; joint action+target choices
# reached 644 tokens in combat and the default 512 rejected every call.
nohup "${LLAMA_SERVER:-$ROOT/llama.cpp/build/bin/llama-server}" \
    -m "$model" -ngl 99 -c "${KEV_CTX:-8192}" -fa on \
    -ctk q8_0 -ctv q8_0 --cache-ram 0 -b 2048 -ub 2048 \
    --host 127.0.0.1 --port "${KEV_PORT:-8080}" ${KEV_EXTRA:-} \
    >>"$ROOT/logs/kev.log" 2>&1 &
pid=$!
write_pidfile "$pid" "$pidfile"
echo "Started Kev (PID $pid, log $ROOT/logs/kev.log)."
