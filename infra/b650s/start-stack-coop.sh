#!/usr/bin/env bash
# Co-op mode: Gemma4-12B + Breeze + STT + Open-P2P 600M, no Kev (~21.8 GB). Run m8py with
# M8PY_CONFIG=configs/b650s-coop.toml ./restart-m8py.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
CHAT_EXTRA="-np 2 -kvu" ./start-chat.sh
./start-breeze.sh
./start-stt.sh
./start-p2p.sh
