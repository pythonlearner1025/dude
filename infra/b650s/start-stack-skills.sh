#!/usr/bin/env bash
# Skill mode: Gemma4-12B (Voice, Reflect) + Breeze + STT; the actor is hosted (OpenRouter), so no
# Kev and no Open-P2P. Then: M8PY_CONFIG=configs/b650s-skills.toml ./restart-m8py.sh and
# ./start-coach.sh.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
CHAT_EXTRA="-np 2 -kvu" ./start-chat.sh
./start-breeze.sh
./start-stt.sh
