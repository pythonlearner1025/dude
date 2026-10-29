#!/usr/bin/env bash
set -euo pipefail

root=/home/minjune/m8work/open-p2p
tools=/home/minjune/m8work/dude/tools/p2p
test_dir=/home/minjune/m8work/p2p-test
mkdir -p "$test_dir" /home/minjune/m8work/run
touch /home/minjune/m8work/run/p2p-instruction.txt

"$root/.venv/bin/python" "$tools/server.py" "$@" &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true' EXIT INT TERM
for _ in $(seq 1 600); do
    [[ -S /tmp/uds.recap ]] && break
    kill -0 "$server_pid"
    sleep 1
done
[[ -S /tmp/uds.recap ]] || { echo "Open-P2P socket did not appear" >&2; exit 1; }
"$root/.venv/bin/python" "$tools/client.py" \
    --window-pid-file /home/minjune/m8work/run/kevin-client.pid \
    --log "$test_dir/actions.jsonl"
