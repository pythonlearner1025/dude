#!/usr/bin/env bash
# Kevin joins the host's co-op game: his own Halo (kevin-client.sh), played by Open-P2P through
# tools/p2p/client.py. m8py runs this with the invite the host sends; start-p2p.sh must be up.
# A new invite replaces the Kevin of the last one.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/_pid.sh"
invite=${1:?usage: kevin-coop.sh <invite-link>}
for name in p2p-client kevin-client; do
    pidfile="$ROOT/run/$name.pid"
    if pidfile_live "$pidfile"; then
        kill "$(pidfile_pid "$pidfile")"
        for _ in $(seq 20); do pidfile_live "$pidfile" || break; sleep 0.25; done
    fi
    rm -f "$pidfile"
done
"$ROOT/scripts/kevin-client.sh" "$invite"
cd "$ROOT/open-p2p"
DISPLAY=:1 XAUTHORITY="$ROOT/run/Xauthority" setsid .venv/bin/python \
    "$ROOT/dude/tools/p2p/client.py" --window-pid-file "$ROOT/run/kevin-client.pid" --wait 120 \
    --mouse-scale 1.28 --keep-focus --log "$ROOT/logs/p2p-actions.jsonl" \
    >>"$ROOT/logs/p2p-client.log" 2>&1 </dev/null &
write_pidfile "$!" "$ROOT/run/p2p-client.pid"
echo "Started the Open-P2P client (PID $!, log $ROOT/logs/p2p-client.log)."
