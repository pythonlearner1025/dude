"""How long a player's order stays inside Kev's 20-line feed window (m8's KEV_FEED_LINES)."""
import json
import sys

trace = [json.loads(line) for line in open(sys.argv[1])]
t0 = trace[0]["t"]


def feed_lines(entry):
    kind, data = entry["kind"], entry["data"]
    if kind == "heard":
        return 1
    if kind == "event":
        return 1 if data.get("text") else 0
    if kind == "kev":
        then = data.get("then") or {}
        return int(data.get("action") not in (None, "nothing")) + int(then.get("action") not in (None, "nothing"))
    if kind == "llm":
        return 1 if data.get("line") else 0
    return 0


for needle in ("ahead of me", "hold your fire", "behind this rock", "where i'm pointing", "clear that area"):
    for i, entry in enumerate(trace):
        if entry["kind"] == "heard" and needle in entry["data"]["text"].lower():
            count = 0
            for later in trace[i + 1:]:
                count += feed_lines(later)
                if count >= 20:
                    print(f'"{entry["data"]["text"]}" at {(entry["t"] - t0) / 60000:.1f} min: '
                          f"out of Kev's window after {(later['t'] - entry['t']) / 1000:.0f} s")
                    break
            else:
                print(f'"{entry["data"]["text"]}": still in the window at session end')
            break

states = [e["data"]["state"] for e in trace if e["kind"] == "event" and isinstance(e["data"].get("state"), dict)]
print("actions offered:", [a.get("name") for a in states[-1].get("actions", [])])
print("state text:", str(states[-1].get("state"))[:500])
