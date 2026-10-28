#!/usr/bin/env bash
# m8's original LLM: Kev-4B Q4_K_M + Gemma4-12B uncensored + Breeze (m8's fast flags), ~22.1 GB.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
KEV_QUANT=Q4_K_M KEV_CTX=4096 KEV_EXTRA="-np 1" ./start-kev.sh
CHAT_EXTRA="-np 2" ./start-chat.sh
./start-breeze.sh
./start-stt.sh
