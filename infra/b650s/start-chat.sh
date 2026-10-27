#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_pid.sh"
mkdir -p "$ROOT/run" "$ROOT/logs"
pidfile="$ROOT/run/chat.pid"
if pidfile_live "$pidfile"; then
    echo "Chat is already running (PID $(pidfile_pid "$pidfile"))."
    exit 0
fi

model="$ROOT/models/gemma-4-12b-hauhaucs/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf"
mmproj="$ROOT/models/gemma-4-12b-hauhaucs/mmproj-Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-BF16.gguf"
nohup "${LLAMA_SERVER:-$ROOT/llama.cpp/build/bin/llama-server}" \
    -m "$model" --mmproj "$mmproj" -ngl 99 -c "${CHAT_CTX:-32768}" -fa on \
    -ctk q8_0 -ctv q8_0 --cache-ram 512 --reasoning off \
    --temp 1.0 --top-k 64 --top-p 0.95 --min-p 0.05 --dry-multiplier 0.8 \
    --host 127.0.0.1 --port "${CHAT_PORT:-8081}" ${CHAT_EXTRA:-} \
    >>"$ROOT/logs/chat.log" 2>&1 &
pid=$!
write_pidfile "$pid" "$pidfile"
echo "Started Gemma chat (PID $pid, log $ROOT/logs/chat.log)."
