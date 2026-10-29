"""The coach's worker: hands each ticket m8py writes (run/tickets/*.json) to Claude Code with Opus
in the skill library, one at a time, oldest first. Claude follows the library's CLAUDE.md: fix
or write skills, test, commit, and write <ticket>.result.md. m8py loads the commit itself.

Usage: python -m m8py.coach --library ~/m8work/kevin-skills --tickets ~/m8work/run/tickets
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

PYTHON = "/home/minjune/m8work/dude/.venv/bin/python"
TOOLS = [
    "Read",
    "Edit",
    "Write",
    "Glob",
    "Grep",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(git add:*)",
    "Bash(git commit:*)",
    f"Bash(PYTHONPATH=/home/minjune/m8work/dude {PYTHON} -m m8py.skilltest:*)",
    "Bash(grep:*)",
    "Bash(tail:*)",
    "Bash(head:*)",
    "Bash(wc:*)",
]


def pending(tickets: Path) -> list[Path]:
    """Tickets with no result yet, oldest first; one review at a time is enough."""
    waiting = sorted(p for p in tickets.glob("*.json") if not p.with_suffix(".result.md").exists())
    reviews = [p for p in waiting if p.stem.endswith("-review")]
    for stale in reviews[:-1]:
        stale.with_suffix(".result.md").write_text("Skipped: a later review covers it.\n")
    return [p for p in waiting if p not in reviews[:-1]]


SIGNED_OUT = ("Please run /login", "authentication_error", "Invalid API key")
# Only the library's CLAUDE.md: not the machine owner's settings, skills, plugins, MCP
# servers or personal CLAUDE.md (which hands all work to Codex).
ISOLATED = [
    "--setting-sources",
    "project,local",
    "--settings",
    json.dumps({"claudeMdExcludes": [str(Path.home() / ".claude" / "CLAUDE.md")]}),
    "--disable-slash-commands",
    "--strict-mcp-config",
    "--tools",
    "Read,Edit,Write,Glob,Grep,Bash",
]


def handle(ticket: Path, library: Path, model: str, timeout: float, claude: str = "claude") -> bool:
    """Runs Claude on one ticket; False if Claude Code isn't signed in (the ticket waits)."""
    prompt = (
        f"Resolve the ticket {ticket}. Follow CLAUDE.md in this directory: change the skills "
        f"or the actor's prompt as the ticket needs, run the skill tests until they print ok, "
        f"commit, then write {ticket.with_suffix('.result.md')}."
    )
    trace = json.loads(ticket.read_text()).get("trace")
    command = [claude, "-p", prompt, "--model", model, "--effort", "high", *ISOLATED]
    command += ["--permission-mode", "acceptEdits", "--add-dir", str(ticket.parent)]
    command += ["--add-dir", str(Path(trace).parent)] if trace else []
    command += ["--output-format", "stream-json", "--verbose", "--allowedTools", *TOOLS]
    # (Claude's shell keeps its cd between commands: git must reach the library from anywhere)
    env = {**os.environ, "GIT_DIR": str(library / ".git"), "GIT_WORK_TREE": str(library)}
    started = time.monotonic()
    with ticket.with_suffix(".log").open("w") as log:
        try:
            done = subprocess.run(
                command,
                cwd=library,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
            status = f"exit {done.returncode}"
        except subprocess.TimeoutExpired:
            status = f"timed out after {timeout:.0f} s"
    if any(sign in ticket.with_suffix(".log").read_text() for sign in SIGNED_OUT):
        print("[coach] Claude Code is not signed in: run `claude` and /login on b650s", flush=True)
        return False
    result = ticket.with_suffix(".result.md")
    if not result.exists():
        result.write_text(
            f"The coach stopped without a result ({status}); see {ticket.stem}.log.\n"
        )
    print(f"[coach] {ticket.stem}: {status} in {time.monotonic() - started:.0f} s", flush=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--tickets", type=Path, required=True)
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--once", action="store_true", help="handle what is waiting, then stop")
    parser.add_argument("--claude", default="claude", help="the Claude Code command")
    args = parser.parse_args()
    args.tickets.mkdir(parents=True, exist_ok=True)
    print(f"[coach] watching {args.tickets}", flush=True)
    while True:
        waiting = pending(args.tickets)
        if waiting:
            if not handle(
                waiting[0], args.library.resolve(), args.model, args.timeout, args.claude
            ):
                time.sleep(300)
        elif args.once:
            return
        else:
            time.sleep(2)


if __name__ == "__main__":
    main()
