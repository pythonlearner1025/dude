"""The coach's eyes: a stretch of a session's trace, turned into one observation packet for Opus.

m8py never writes to the coach. The coach reads the trace on a heartbeat and builds a packet of
everything since its last one: what the player said, what Kevin said, the game's events, the
actor's decisions, how each skill ended, the commands Halo got, Kevin's and the player's state
over time, and frames of the player's view. `packet.json` holds it as data; `packet.md` is the
same, merged into one timeline, which is what Opus reads.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STATE_EVERY = 15.0  # seconds between state lines when nothing changes
MAX_FRAMES = 12


def rows_between(trace: Path, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    rows = []
    with trace.open() as lines:
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a line still being written
            if start_ms < int(row["t"]) <= end_ms:
                rows.append(row)
    return rows


def active(rows: list[dict[str, Any]]) -> bool:
    """Whether anything happened worth a look, in a game (not the menus): the player spoke, a
    skill ended, a game event, or a decision that wasn't a heartbeat keep."""
    if not any(row["kind"] == "state" for row in rows):
        return False
    for row in rows:
        kind, data = row["kind"], row["data"]
        if kind == "heard" and data.get("text", "").strip():
            return True
        if kind in ("skill", "event"):
            return True
        if kind == "decision" and data.get("reasons") not in (["heartbeat"], None):
            return True
    return False


def clock(ms: int) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ms / 1000)) + f".{ms % 1000 // 100}"


def point(pos: Any) -> str:
    return f"({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})" if pos else "?"


def gist(state: dict[str, Any]) -> tuple:
    """What a state line says, coarsely: a new line only when this changes."""
    kevin, player = state.get("kevin") or {}, state.get("player") or {}

    def near(pos: Any) -> tuple:
        return tuple(round(v / 2) for v in pos[:2]) if pos else ()

    def tenth(value: Any) -> int:
        return round(10 * (value if value is not None else 1))

    return (
        near(kevin.get("pos")),
        kevin.get("activity"),
        kevin.get("target"),
        str(kevin.get("vehicle")),
        str(player.get("vehicle")),
        tenth(kevin.get("health")),
        tenth(kevin.get("shields")),
        near(player.get("pos")),
        round((player.get("facing") or 0) / 30),
        tenth(player.get("health")),
        (player.get("aim") or {}).get("label"),
        tuple(
            (e.get("id"), round((e.get("distance_m") or 0) / 5)) for e in state.get("enemies") or []
        ),
        str(state.get("running", "")).split(" (for")[0],
    )


def build(
    trace: Path,
    start_ms: int,
    end_ms: int,
    ident: str,
    library: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """One packet: the session's rows in (start_ms, end_ms], as a timeline of typed entries."""
    rows = rows_between(trace, start_ms, end_ms)
    timeline: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    counts = {
        "player_lines": 0,
        "decisions": 0,
        "heartbeat_keeps": 0,
        "skills_done": 0,
        "skills_failed": 0,
        "actor_errors": 0,
        "friendly_fire": 0,
        "kevin_deaths": 0,
    }
    level, last_state, last_gist = None, 0, None
    for row in rows:
        t, kind, data = int(row["t"]), row["kind"], row["data"]
        if kind == "heard" and data.get("text", "").strip():
            counts["player_lines"] += 1
            timeline.append({"t": t, "type": "player", "said": data["text"].strip()})
        elif kind == "voice" and data.get("text"):
            timeline.append({"t": t, "type": "kevin_said", "said": data["text"]})
        elif kind == "event":
            text = str(data.get("text", ""))
            counts["friendly_fire"] += text.count("Chief shot Kevin")
            counts["kevin_deaths"] += text.count("Kevin died")
            timeline.append({"t": t, "type": "game", "event": text})
        elif kind == "decision":
            if "answer" not in data:
                counts["actor_errors"] += 1
                timeline.append(
                    {
                        "t": t,
                        "type": "decision",
                        "why": data.get("reasons"),
                        "error": data.get("error"),
                    }
                )
                continue
            counts["decisions"] += 1
            if data.get("kind") == "keep" and data.get("reasons") == ["heartbeat"]:
                counts["heartbeat_keeps"] += 1
                continue
            entry = {
                "t": t,
                "type": "decision",
                "why": data["reasons"],
                "answer": data["answer"],
                "ms": data.get("ms"),
            }
            if data.get("retry"):
                entry["retry"] = data["retry"]
            if data.get("error"):
                entry["error"] = data["error"]
            timeline.append(entry)
        elif kind == "skill":
            ended = "done" if "done" in data else "failed"
            counts[f"skills_{ended}"] += 1
            timeline.append(
                {
                    "t": t,
                    "type": "skill",
                    "skill": data["skill"],
                    "args": data.get("args", {}),
                    ended: data.get(ended),
                }
            )
        elif kind == "body":
            for sent in data.get("sent", []):
                timeline.append(
                    {
                        "t": t,
                        "type": "command",
                        "action": sent.get("action"),
                        "option": sent.get("option"),
                    }
                )
        elif kind == "library":
            timeline.append(
                {
                    "t": t,
                    "type": "library",
                    "head": data.get("head"),
                    "skills": len(data.get("skills", [])),
                    "errors": data.get("errors"),
                }
            )
        elif kind == "state":
            level = data.get("level") or level
            now = gist(data)
            if now != last_gist or t - last_state >= STATE_EVERY * 1000:
                last_state, last_gist = t, now
                timeline.append(
                    {"t": t, "type": "state", **{k: v for k, v in data.items() if k != "level"}}
                )
        elif kind == "view":
            frames.append({"t": t, "file": data["file"], "why": data.get("why", "")})
    if len(frames) > MAX_FRAMES:  # the ones next to the player's lines first, then spread out
        spoken = [f for f in frames if f["why"] == "the player spoke"]
        rest = [f for f in frames if f["why"] != "the player spoke"]
        keep = spoken[-MAX_FRAMES:]
        room = MAX_FRAMES - len(keep)
        keep += rest[:: max(1, len(rest) // room)][:room] if room else []
        frames = sorted(keep, key=lambda f: f["t"])
    timeline += [{"t": f["t"], "type": "frame", "file": f["file"], "why": f["why"]} for f in frames]
    timeline.sort(key=lambda e: e["t"])
    return {
        "id": ident,
        "session": trace.parent.name,
        "level": level,
        "window": {"from": start_ms, "to": end_ms, "seconds": round((end_ms - start_ms) / 1000)},
        "library": library,
        "previous": previous,
        "counts": counts,
        "frames": frames,
        "timeline": timeline,
    }


def line(entry: dict[str, Any]) -> str:
    kind = entry["type"]
    if kind == "player":
        return f'PLAYER   "{entry["said"]}"'
    if kind == "kevin_said":
        return f'KEVIN    "{entry["said"]}"'
    if kind == "game":
        return f"GAME     {entry['event']}"
    if kind == "decision":
        if "answer" not in entry:
            return f"ACTOR    error: {entry.get('error')} <- {' / '.join(entry['why'] or [])}"
        answer = entry["answer"] + (f" -> retry {entry['retry']}" if entry.get("retry") else "")
        failed = f"  (could not run: {entry['error']})" if entry.get("error") else ""
        return f"ACTOR    {' / '.join(entry['why'])} => {answer} ({entry['ms']} ms){failed}"
    if kind == "skill":
        args = " ".join(f"{k}={v}" for k, v in entry["args"].items())
        how = f"done: {entry['done']}" if "done" in entry else f"FAILED: {entry['failed']}"
        return f"SKILL    {entry['skill']} {args}".rstrip() + f" -> {how}"
    if kind == "command":
        return f"HALO     {entry['action']} {entry.get('option') or ''}".rstrip()
    if kind == "library":
        return f"LIBRARY  reloaded at {entry.get('head')}: {entry['skills']} skills" + (
            f", errors {entry['errors']}" if entry.get("errors") else ""
        )
    if kind == "frame":
        return f"FRAME    {entry['file']} ({entry['why']})"
    kevin, player = entry.get("kevin") or {}, entry.get("player") or {}
    aim = player.get("aim") or {}
    enemies = entry.get("enemies") or []
    near = ", ".join(
        f"{e['kind']}#{e['id']} {e.get('distance_m', 0):.0f} m"
        + ("" if e.get("in_sight") else " unseen")
        for e in enemies[:4]
    )
    target = f" at {kevin['target']}" if kevin.get("target") else ""

    def riding(who: dict[str, Any]) -> str:
        ride = who.get("vehicle") or {}
        return f", in a {ride.get('name')} ({ride.get('seat')})" if ride else ""

    return (
        f"STATE    Kevin {point(kevin.get('pos'))} facing {kevin.get('facing', 0):.0f}°, "
        f"health {kevin.get('health', 1):.0%} shields {kevin.get('shields', 1):.0%}, "
        f"{kevin.get('activity', '?')}{target}{riding(kevin)}"
        f" | player {point(player.get('pos'))} facing {player.get('facing', 0):.0f}°, "
        f"health {player.get('health', 1):.0%}{riding(player)}, aim {aim.get('label', 'nothing')}"
        + (f" {aim.get('distance_m', 0):.0f} m" if aim else "")
        + f" | enemies: {near or 'none'}"
        + (f" | running {entry['running']}" if entry.get("running") else "")
    )


def render(packet: dict[str, Any]) -> str:
    window, counts, library = packet["window"], packet["counts"], packet["library"]
    head = [
        f"# Observation {packet['id']}",
        "",
        f"Level {packet['level']}, {clock(window['from'])} to {clock(window['to'])} "
        f"({window['seconds']} s).",
        "Counts: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in counts.items()) + ".",
        f"Library now at {library.get('head')}; your commits since the last observation: "
        + ("; ".join(library.get("since_last") or []) or "none")
        + ". LIBRARY lines below show when the game loaded a version.",
    ]
    if packet.get("previous"):
        head.append(
            f"Last observation ({packet['previous']['id']}), you wrote: "
            f"{packet['previous'].get('result', '').strip()}"
        )
    head += ["", "## Timeline (frames are images: Read them)", ""]
    body = [f"{clock(e['t'])}  {line(e)}" for e in packet["timeline"]]
    return "\n".join(head + body) + "\n"
