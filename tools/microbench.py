"""Times Kev (/v1/systemone) and the chat LLM (stream + vision) with m8-shaped prompts."""
import base64, json, statistics, sys, time
from pathlib import Path
import httpx

persona = Path.home() / "m8work/dude/personas/kevin"
system = (persona / "system_prompt.txt").read_text().strip().replace("{player}", "Chasm")
story = (persona / "levels/a30.txt").read_text().strip().replace("{player}", "Chasm")
feed = [
    "Chasm: Kevin, you with me?", "Kevin: [cocky] Always, Chasm. Try to keep up.",
    "A grunt shouts somewhere ahead.", "Kevin follows Chasm.", "Chasm shot a grunt.",
    "Cortana over the radio: \"Covenant dropship inbound, take cover.\"",
    "Kevin takes cover.", "Kevin's shields broke.", "Chasm: Kevin, grab that shotgun.",
] * 2 + ["Chasm: What do you see over there?"]
state = ("Kevin: shields low, holding an assault rifle (32 rounds), behind a rock. Chasm: close by "
         "on the left. Enemies: two grunts close (12 m) ahead, an elite far (40 m) to the right.")
actions = {"nothing": "Kevin carries on as he is", "follow": "Kevin follows Chasm",
           "stay": "Kevin stays where he is", "shoot": "Kevin shoots at an enemy",
           "take_cover": "Kevin takes cover", "rush": "Kevin rushes an enemy",
           "grenade": "Kevin throws a grenade", "search_weapons": "Kevin looks around for weapons",
           "look": "Kevin takes a look at something Chasm wants him to see",
           "go_to": "Kevin goes to a spot Chasm can see", "reload": "Kevin reloads"}
prompt = "\n\n".join([system, story, "\n".join(feed[:-1]), "Right now: " + state, feed[-1]])
c = httpx.Client(timeout=120)

def kev(questions):
    t = time.perf_counter()
    r = c.post("http://127.0.0.1:8080/v1/systemone", json={"model": "kev-latest", "state": prompt, "questions": questions})
    return (time.perf_counter() - t) * 1000, r.json()

do = {"do": {"type": "choice", "instructions": "Which of these does Kevin do now?", "criteria": actions}}
speak = {"speak": {"type": "noul", "instructions": "Should Kevin speak now?"}}
ms = [kev(do)[0] for _ in range(6)]
_, body = kev(do)
print(f"KEV prompt ~{len(prompt)//4} tok | do: cold {ms[0]:.0f} ms, warm p50 {statistics.median(ms[1:]):.0f} ms | answer {body['answers']['do']['choice']} conf {body['answers']['do'].get('confidence', 0):.2f} | usage {body.get('usage')}")
ms = [kev(speak)[0] for _ in range(5)]
print(f"KEV speak p50 {statistics.median(ms):.0f} ms -> {kev(speak)[1]['answers']}")

msgs = [{"role": "system", "content": system}, {"role": "user", "content": story + "\n" + "\n".join(feed[:-1])},
        {"role": "user", "content": "Right now: " + state + "\n" + feed[-1]}]
for run in range(3):
    t = time.perf_counter(); first = None; text = ""; timings = None
    with c.stream("POST", "http://127.0.0.1:8081/v1/chat/completions", json={"messages": msgs, "temperature": 1.0, "stream": True}) as r:
        for line in r.iter_lines():
            if not line.startswith("data: ") or line[6:].strip() == "[DONE]":
                continue
            ch = json.loads(line[6:]); timings = ch.get("timings") or timings
            d = (ch.get("choices") or [{}])[0].get("delta", {}).get("content")
            if d:
                first = first or (time.perf_counter() - t) * 1000; text += d
    print(f"LLM run{run}: first token {first:.0f} ms, total {(time.perf_counter()-t)*1000:.0f} ms, "
          f"prompt_n {timings and timings.get('prompt_n')} cache_n {timings and timings.get('cache_n')} "
          f"gen {timings and round(timings.get('predicted_per_second', 0))} tok/s | {text.strip()[:160]!r}")

img = base64.b64encode((Path.home() / "m8work/logs/halo-first-start.png").read_bytes()).decode()
t = time.perf_counter()
r = c.post("http://127.0.0.1:8081/v1/chat/completions", json={"temperature": 1.0, "messages": [
    {"role": "system", "content": "You're the eyes of Kevin, Chasm's teammate in Halo: you're shown what Chasm is looking at. Say plainly what's there, in a sentence or two: what you see, not anyone's lines."},
    {"role": "user", "content": [{"type": "text", "text": "Here's what Chasm is looking at. What's there?"},
                                 {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img}}]}]})
print(f"VISION {(time.perf_counter()-t)*1000:.0f} ms | {r.json()['choices'][0]['message']['content'].strip()[:200]!r}")
