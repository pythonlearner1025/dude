"""The coach: Claude Code with Opus, watching Kevin play. m8py never asks it anything. On a
heartbeat it takes everything the session's trace gathered since its last look (m8py/observe.py
turns it into one packet: transcript, Kevin's lines, game events, the actor's decisions, skill
endings, Halo commands, state over time, frames), and Claude, in the skill library, decides what
to change: it follows the library's CLAUDE.md, tests, commits and writes <packet>/result.md. A
look that takes a while just makes the next packet longer, so nothing queues up.

Usage: python -m m8py.coach --library ~/m8work/kevin-skills --logs ~/m8work/dude/logs
    --out ~/m8work/run/observations
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .observe import active, build, render, rows_between

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
QUIET = 60.0  # seconds without a trace line: the session paused or ended, look at what's left
LONGEST = 600.0  # seconds: a packet covers at most the last ten minutes


def run_claude(
    prompt: str,
    library: Path,
    dirs: list[Path],
    log: Path,
    model: str,
    effort: str,
    timeout: float,
    claude: str = "claude",
) -> str | None:
    """Runs Claude Code in the library; its status, or None if it isn't signed in."""
    command = [claude, "-p", prompt, "--model", model, "--effort", effort, *ISOLATED]
    command += ["--permission-mode", "acceptEdits"]
    for directory in dirs:
        command += ["--add-dir", str(directory)]
    command += ["--output-format", "stream-json", "--verbose", "--allowedTools", *TOOLS]
    # (Claude's shell keeps its cd between commands: git must reach the library from anywhere)
    env = {**os.environ, "GIT_DIR": str(library / ".git"), "GIT_WORK_TREE": str(library)}
    with log.open("w") as out:
        try:
            done = subprocess.run(
                command,
                cwd=library,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
            status = f"exit {done.returncode}"
        except subprocess.TimeoutExpired:
            status = f"timed out after {timeout:.0f} s"
    if any(sign in log.read_text() for sign in SIGNED_OUT):
        return None
    return status


def asking(packet_dir: Path, seconds: int) -> str:
    return (
        f"Observe {packet_dir / 'packet.md'}: {seconds} s of Kevin's play. Follow CLAUDE.md in "
        f"this directory: read notes.md, the packet and the frames you need, change what most "
        f"hurt Kevin as the player's teammate (if anything), run the skill tests until they "
        f"print ok, commit, update notes.md, then write {packet_dir / 'result.md'}."
    )


def git(library: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(library), *args], capture_output=True, text=True
    ).stdout.strip()


def first_ms(trace: Path) -> int:
    with trace.open() as lines:
        return int(json.loads(next(lines))["t"]) - 1


def last_ms(trace: Path) -> int:
    with trace.open("rb") as lines:
        lines.seek(max(0, trace.stat().st_size - 65536))
        for line in reversed(lines.read().splitlines()):
            try:
                return int(json.loads(line)["t"])
            except (ValueError, KeyError):
                continue
    return 0


def newest_trace(logs: Path, within: float) -> Path | None:
    traces = [p for p in logs.glob("*/trace.jsonl") if time.time() - p.stat().st_mtime < within]
    return max(traces, key=lambda p: p.stat().st_mtime, default=None)


def look(
    trace: Path,
    library: Path,
    out: Path,
    every: float,
    model: str,
    effort: str,
    timeout: float,
    claude: str,
) -> str | None:
    """One heartbeat for one session: builds a packet and hands it to Claude, if it's time and
    something happened. Returns "looked", "waiting" or None (Claude Code is signed out)."""
    session = out / trace.parent.name
    session.mkdir(parents=True, exist_ok=True)
    state_path = session / "state.json"
    state: dict[str, Any] = (
        json.loads(state_path.read_text())
        if state_path.exists()
        else {
            "seq": 0,
            "last": first_ms(trace),
            "head": git(library, "rev-parse", "--short", "HEAD"),
        }
    )
    end = last_ms(trace)
    quiet = time.time() - trace.stat().st_mtime > QUIET
    if end <= state["last"] or (end - state["last"] < every * 1000 and not quiet):
        return "waiting"
    if not active(rows_between(trace, state["last"], end)):
        if quiet:  # nothing but the game idling: skip it for good
            state["last"] = end
            state_path.write_text(json.dumps(state))
        return "waiting"
    state["seq"] += 1
    start = max(state["last"], end - int(LONGEST * 1000))
    packet_dir = session / f"{state['seq']:03d}"
    packet_dir.mkdir(exist_ok=True)
    head = git(library, "rev-parse", "--short", "HEAD")
    since = git(library, "log", "--format=%h %s", f"{state['head']}..HEAD")
    previous = None
    before = session / f"{state['seq'] - 1:03d}" / "result.md"
    if before.exists():
        previous = {
            "id": f"{trace.parent.name}-{state['seq'] - 1:03d}",
            "result": before.read_text(),
        }
    packet = build(
        trace,
        start,
        end,
        f"{trace.parent.name}-{state['seq']:03d}",
        {"head": head, "since_last": since.splitlines() if since else []},
        previous,
    )
    for frame in packet["frames"]:  # the packet keeps its own copies of the frames it lists
        source = trace.parent / frame["file"]
        if source.exists():
            (packet_dir / "frames").mkdir(exist_ok=True)
            shutil.copy(source, packet_dir / "frames" / source.name)
        frame["file"] = str(packet_dir / "frames" / source.name)
    for entry in packet["timeline"]:
        if entry["type"] == "frame":
            entry["file"] = str(packet_dir / "frames" / Path(entry["file"]).name)
    (packet_dir / "packet.json").write_text(json.dumps(packet, indent=1))
    (packet_dir / "packet.md").write_text(render(packet))
    window = packet["window"]["seconds"]
    print(f"[coach] {packet['id']}: {window} s, {packet['counts']}", flush=True)
    started = time.monotonic()
    status = run_claude(
        asking(packet_dir, window),
        library,
        [packet_dir],
        packet_dir / "claude.log",
        model,
        effort,
        timeout,
        claude,
    )
    if status is None:
        print("[coach] Claude Code is not signed in: see infra/b650s/README.md", flush=True)
        shutil.rmtree(packet_dir)
        return None
    if not (packet_dir / "result.md").exists():
        (packet_dir / "result.md").write_text(f"The coach stopped without a result ({status}).\n")
    print(f"[coach] {packet['id']}: {status} in {time.monotonic() - started:.0f} s", flush=True)
    state.update(last=end, head=head)
    state_path.write_text(json.dumps(state))
    return "looked"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--logs", type=Path, required=True, help="m8py's session logs")
    parser.add_argument("--out", type=Path, required=True, help="where packets and results go")
    parser.add_argument("--every", type=float, default=60, help="seconds between looks, at least")
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--effort", default="high", help="low, medium, high, xhigh or max")
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument(
        "--once", action="store_true", help="look once if there's anything, then stop"
    )
    parser.add_argument("--claude", default="claude", help="the Claude Code command")
    args = parser.parse_args()
    library = args.library.resolve()
    print(f"[coach] watching {args.logs}", flush=True)
    while True:
        trace = newest_trace(args.logs, within=3600)
        outcome = "waiting"
        if trace:
            outcome = look(
                trace,
                library,
                args.out,
                args.every,
                args.model,
                args.effort,
                args.timeout,
                args.claude,
            )
        if args.once:
            return
        time.sleep(300 if outcome is None else 2)


if __name__ == "__main__":
    main()
