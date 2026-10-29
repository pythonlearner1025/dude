"""Shows what the coach did on a ticket, from its stream-json log (<ticket>.log): the session's
model and tools, each tool call, what Claude said, and the final result.

Usage: python tools/coach_log.py ~/m8work/run/tickets/<ticket>.log
"""

import json
import sys

for line in open(sys.argv[1]):
    try:
        row = json.loads(line)
    except ValueError:
        print("RAW", line[:200].rstrip())
        continue
    if row.get("type") == "system" and row.get("subtype") == "init":
        print("START", row.get("model"), row.get("tools"), "skills:", row.get("skills"))
    if row.get("type") == "result":
        seconds, turns = row.get("duration_ms", 0) / 1000, row.get("num_turns")
        cost = row.get("total_cost_usd", 0)
        print(f"RESULT {row.get('subtype')} {seconds:.0f} s, {turns} turns, ${cost:.2f}")
        print(row.get("result", ""))
    message = row.get("message")
    for part in (message.get("content") or []) if isinstance(message, dict) else []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "tool_use":
            print("TOOL", part["name"], json.dumps(part["input"])[:160])
        elif part.get("type") == "text" and row.get("type") == "assistant":
            print("SAYS", part["text"][:300].replace("\n", " "))
        elif part.get("type") == "tool_result" and part.get("is_error"):
            print("  ERROR", str(part.get("content"))[:200].replace("\n", " "))
