"""Re-runs the coach on an observation packet with another model or effort, on a fresh clone of
the skill library at a given commit, and prints the time, turns, cost and what it committed.

Usage: python tools/coach_bench.py <packet dir> <library commit> <model> <effort> <workdir>
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from m8py.coach import asking, run_claude

packet, base, model, effort, work = Path(sys.argv[1]), *sys.argv[2:5], Path(sys.argv[5])
library, copy = work / "library", work / "packet"
subprocess.run(["git", "clone", "-q", str(Path.home() / "m8work/kevin-skills"), str(library)])
subprocess.run(["git", "-C", str(library), "checkout", "-q", base], check=True)
for key, value in (("user.name", "Kevin coach"), ("user.email", "coach@localhost")):
    subprocess.run(["git", "-C", str(library), "config", key, value], check=True)
shutil.copytree(packet, copy, ignore=shutil.ignore_patterns("claude.log", "result.md"))
text = (copy / "packet.md").read_text().replace(str(packet), str(copy))
(copy / "packet.md").write_text(text)
seconds = json.loads((copy / "packet.json").read_text())["window"]["seconds"]
claude = str(Path.home() / ".npm-global/bin/claude")
status = run_claude(
    asking(copy, seconds), library, [copy], copy / "claude.log", model, effort, 900, claude
)
result = {}
for line in (copy / "claude.log").read_text().splitlines():
    if '"type":"result"' in line:
        result = json.loads(line)
print(
    f"{packet.name} {model} {effort}: {status}, {result.get('duration_ms', 0) / 1000:.0f} s, "
    f"{result.get('num_turns')} turns, ${result.get('total_cost_usd', 0):.2f}"
)
log = ["git", "-C", str(library), "log", "--format=%h %s", f"{base}..HEAD"]
print(subprocess.run(log, capture_output=True, text=True).stdout.strip() or "(no commit)")
