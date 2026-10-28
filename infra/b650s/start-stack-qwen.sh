#!/usr/bin/env bash
# Fallback LLM: Kev-4B Q8_0 + Qwen3.5-9B uncensored + Breeze (m8's fast flags), ~21.9 GB.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
KEV_CTX=4096 KEV_EXTRA="-np 1" ./start-kev.sh
CHAT_EXTRA="-np 2 -kvu" ./start-chat-qwen.sh
./start-breeze.sh
./start-stt.sh
