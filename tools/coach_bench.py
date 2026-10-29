"""Re-runs a coach ticket with another model or effort, on a fresh clone of the skill library at
the commit before the coach's own fix, and prints the time, turns, cost and diff.

Usage: python tools/coach_bench.py <ticket.json> <base commit> <model> <effort> <workdir>
"""

import json
import subprocess
import sys
from pathlib import Path

from m8py.coach import handle

ticket, base, model, effort, work = Path(sys.argv[1]), *sys.argv[2:5], Path(sys.argv[5])
library, tickets = work / "library", work / "tickets"
subprocess.run(["git", "clone", "-q", str(Path.home() / "m8work/kevin-skills"), str(library)])
subprocess.run(["git", "-C", str(library), "checkout", "-q", base], check=True)
for key, value in (("user.name", "Kevin coach"), ("user.email", "coach@localhost")):
    subprocess.run(["git", "-C", str(library), "config", key, value], check=True)
tickets.mkdir(parents=True, exist_ok=True)
copy = tickets / ticket.name
copy.write_text(ticket.read_text())
handle(copy, library, model, 900, str(Path.home() / ".npm-global/bin/claude"), effort)
result = next(
    json.loads(line)
    for line in copy.with_suffix(".log").read_text().splitlines()[::-1]
    if line.startswith('{"type":"result"')
)
log = ["git", "-C", str(library), "log", "--format=%h %s", f"{base}..HEAD"]
print(
    f"{ticket.stem} {model} {effort}: {result['duration_ms'] / 1000:.0f} s, "
    f"{result['num_turns']} turns, ${result['total_cost_usd']:.2f}, "
    f"{result['usage']['output_tokens']} output tokens"
)
print(subprocess.run(log, capture_output=True, text=True).stdout.strip() or "(no commit)")
print(
    subprocess.run(
        ["git", "-C", str(library), "diff", "--stat", base], capture_output=True, text=True
    ).stdout.strip()
)
