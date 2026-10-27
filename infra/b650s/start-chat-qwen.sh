#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_pid.sh"
mkdir -p "$ROOT/run" "$ROOT/logs"
pidfile="$ROOT/run/chat-qwen.pid"
if pidfile_live "$pidfile"; then
    echo "Qwen chat is already running (PID $(pidfile_pid "$pidfile"))."
    exit 0
fi

model="$ROOT/models/qwen3.5-9b-hauhaucs/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf"
mmproj="$ROOT/models/qwen3.5-9b-hauhaucs/mmproj-Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-BF16.gguf"
nohup "${LLAMA_SERVER:-$ROOT/llama.cpp/build/bin/llama-server}" \
    -m "$model" --mmproj "$mmproj" -ngl 99 -c "${CHAT_CTX:-32768}" -fa on \
    -ctk q8_0 -ctv q8_0 --cache-ram 512 --reasoning off \
    --temp 0.7 --top-k 20 --top-p 0.8 --min-p 0 \
    --host 127.0.0.1 --port "${CHAT_PORT:-8081}" ${CHAT_EXTRA:-} \
    >>"$ROOT/logs/chat-qwen.log" 2>&1 &
pid=$!
write_pidfile "$pid" "$pidfile"
echo "Started Qwen chat (PID $pid, log $ROOT/logs/chat-qwen.log)."
