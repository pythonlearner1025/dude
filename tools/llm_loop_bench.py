"""How fast can an LLM close Kevin's action loop? Times one step per action unit against an
OpenAI-compatible chat endpoint (llama.cpp here): a fixed system prompt with Kevin's skill API
(cached after the first step) and a fresh game-state snapshot each step.

Units: primitive (one frame's keys/mouse), skill (one skill call), plan (up to five calls),
write (a new skill as Python), the terse forms of the first two ("w 12 -3 1", "flank elite"; a
GBNF grammar, llama.cpp only), and skill+image (one skill call from a screenshot, cycling
through the images given so each step encodes a new one).

Usage: python tools/llm_loop_bench.py --url http://127.0.0.1:8081 --label gemma-12b [--steps 12]
       [--image a.png,b.png] [--slot 1] [--probe]
       python tools/llm_loop_bench.py --url https://openrouter.ai/api --key-env OPENROUTER_API_KEY \
       --model deepseek/deepseek-v4.1-flash-1017 --provider together --label ds-v4.1-flash
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
import statistics
import time
import urllib.request

SKILLS = {
    "follow": "stay 3-6 m behind the player, keep line of sight",
    "move_to": "walk to a named place or a bearing/distance, path around obstacles",
    "attack": "aim at and shoot a target until it dies or leaves view; reload when empty",
    "take_cover": "move behind the nearest cover between you and a threat, crouch",
    "flank": "circle left or right of a target at 10-15 m, then attack it",
    "hold": "stay where you are and watch a bearing; shoot only if fired on",
    "hold_fire": "stop shooting until told otherwise",
    "throw_grenade": "throw a grenade at a target or position",
    "melee": "melee the nearest enemy in reach",
    "pick_up": "walk to and pick up a named weapon, ammo or health pack",
    "retreat": "back away from threats toward the player",
    "look_at": "turn to face a target, bearing or the player's aim point",
}
API = """Body API available to skills (Python, runs at the game's 30 Hz tick):
  me.pos, me.yaw, me.pitch, me.health, me.shield, me.ammo, me.weapon, me.grenades
  player.pos, player.aim_point, player.yaw
  world.enemies() -> [Enemy(id, kind, pos, health, visible)], world.cover_near(pos, r) -> [Point]
  world.path(a, b) -> [Point], world.items_near(pos, r) -> [Item(kind, pos)]
  body.move_toward(point, speed=1.0)   # sets W/A/S/D for this tick
  body.aim_at(point, max_turn_deg=20)  # sets mouse delta for this tick
  body.fire(on=True), body.crouch(on=True), body.jump(), body.reload(), body.grenade()
  yield                                # end this tick; resume next tick
"""
SYSTEM = (
    "You are the body controller of Kevin, a Marine and the player's co-op teammate in Halo CE "
    "(a first-person shooter). Each message is the game state right now. Keep Kevin alive, "
    "useful and in character: protect the player, follow their orders exactly, and react to "
    "threats. Orders come from the player's voice and stay in force until changed.\n\n"
    "Skills Kevin can run (each runs by itself until done or replaced):\n"
    + "\n".join(f"- {name}(target): {what}" for name, what in SKILLS.items())
    + "\n\n"
    + API
    + "\nRules: answer only in the requested format; never explain; choose the single best "
    "option for this moment; prefer continuing the current skill unless something changed."
)
KINDS = ["grunt", "jackal", "elite", "hunter"]
ORDERS = ["follow me", "flank right", "take cover", "hold fire", "clear the room", "none"]


def state(step: int, rng: random.Random) -> str:
    enemies = [
        f"{rng.choice(KINDS)}#{i} {rng.randint(5, 40)} m bearing {rng.randint(-180, 180)}° "
        f"health {rng.randint(10, 100)}% {'visible' if rng.random() < 0.7 else 'heard'}"
        for i in range(rng.randint(0, 4))
    ]
    return (
        f"Tick {1000 + step * 6}. Kevin: health {rng.randint(20, 100)}%, shield "
        f"{rng.randint(0, 100)}%, assault rifle {rng.randint(0, 60)}/{rng.randint(0, 240)}, "
        f"grenades {rng.randint(0, 4)}, crouched {rng.random() < 0.3}.\n"
        f"Player: {rng.randint(1, 20)} m away bearing {rng.randint(-180, 180)}°, aiming at "
        f"{rng.choice(['a rock', 'a doorway', 'an elite', 'the ridge', 'nothing'])}, "
        f"shield {rng.randint(0, 100)}%.\n"
        f"Enemies: {'; '.join(enemies) or 'none'}.\n"
        f"Cover: rock 4 m bearing 40°, crate 7 m bearing -65°.\n"
        f"Current skill: {rng.choice(list(SKILLS))}. Order in force: {rng.choice(ORDERS)}.\n"
        f'Player just said: "{rng.choice(ORDERS + ["behind you!", "nice shot"])}"'
    )


SKILL_CALL = {
    "type": "object",
    "properties": {"skill": {"enum": list(SKILLS)}, "target": {"type": "string", "maxLength": 24}},
    "required": ["skill", "target"],
}
UNITS = {
    "primitive": (
        "Give this tick's input only.",
        {
            "type": "object",
            "properties": {
                "keys": {"enum": ["", "w", "a", "s", "d", "wa", "wd", "sa", "sd"]},
                "mouse": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": -400, "maximum": 400},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "fire": {"type": "boolean"},
            },
            "required": ["keys", "mouse", "fire"],
        },
        48,
    ),
    "skill": ("Pick the skill to run now.", SKILL_CALL, 48),
    "plan": (
        "Plan the next few seconds as up to five skills in order.",
        {"type": "array", "items": SKILL_CALL, "minItems": 1, "maxItems": 5},
        200,
    ),
    "primitive-terse": (
        'Give this tick\'s input only, as: keys dx dy fire (e.g. "wa 12 -3 1").',
        'root ::= ("w"|"a"|"s"|"d"|"wa"|"wd"|"sa"|"sd"|"-") " " int " " int " " ("0"|"1")\n'
        'int ::= "-"? [0-9] [0-9]? [0-9]?',
        12,
    ),
    "skill-terse": (
        'Pick the skill to run now, as: skill target (e.g. "flank elite#2").',
        "root ::= (" + "|".join(f'"{name}"' for name in SKILLS) + ') " " [a-z0-9#]{1,12}',
        12,
    ),
    "write": (
        'No skill fits the player\'s order "flank right and push them off the ridge". Write one '
        "new skill as a Python generator function using the body API. Code only.",
        None,
        400,
    ),
}


class Target:
    """An OpenAI-compatible endpoint: a local llama.cpp server (grammars, slots, timings) or a
    hosted one such as OpenRouter (key from --key-env, a pinned provider, reasoning on or off)."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.url, self.slot, self.model = args.url, args.slot, args.model
        self.local = args.model is None
        self.headers = {"Content-Type": "application/json"}
        if args.key_env:
            self.headers["Authorization"] = f"Bearer {os.environ[args.key_env]}"
        self.extra: dict = {}
        if not self.local:
            self.extra = {"model": args.model, "reasoning": {"enabled": args.reasoning}}
            if args.provider:
                self.extra["provider"] = {"only": [args.provider], "allow_fallbacks": False}

    def body(self, messages: list, limit: int, schema: object, temperature: float) -> dict:
        body = {"messages": messages, "temperature": temperature, "max_tokens": limit, **self.extra}
        if self.local:
            body["chat_template_kwargs"] = {"enable_thinking": False}
            if isinstance(schema, str):
                body["grammar"] = schema
            elif schema:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "schema": schema},
                }
            if self.slot is not None:
                body["id_slot"] = self.slot
        elif limit < 100:  # room for the answer after any reasoning
            body["max_tokens"] = limit + (2000 if self.extra["reasoning"]["enabled"] else 0)
        return body

    def post(self, body: dict) -> tuple[float, float, int, dict, str]:
        """Streams one completion: (s to first answer token, total s, tokens, timings, text).
        Hosted endpoints report usage, not llama.cpp timings: prompt and cached tokens."""
        request = urllib.request.Request(
            f"{self.url}/v1/chat/completions",
            data=json.dumps(
                {**body, "stream": True, "stream_options": {"include_usage": True}}
            ).encode(),
            headers=self.headers,
        )
        started = time.perf_counter()
        first, tokens, timings, text = None, 0, {}, ""
        with urllib.request.urlopen(request, timeout=120) as response:
            for raw in response:
                line = raw.decode().strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                chunk = json.loads(line[6:])
                timings = chunk.get("timings") or timings
                if (usage := chunk.get("usage")) and "prompt_ms" not in timings:
                    details = usage.get("prompt_tokens_details") or {}
                    timings = {
                        "predicted_n": usage.get("completion_tokens", 0),
                        "prompt_n": usage.get("prompt_tokens", 0)
                        - (details.get("cached_tokens") or 0),
                    }
                choices = chunk.get("choices") or []
                if choices and (delta := choices[0].get("delta", {}).get("content")):
                    first = first or time.perf_counter() - started
                    tokens += 1
                    text += delta
        total = time.perf_counter() - started
        return first or total, total, timings.get("predicted_n", tokens), timings, text


TERSE = {
    "skill-terse": re.compile(r"^\s*(" + "|".join(SKILLS) + r") \S+\s*$"),
    "primitive-terse": re.compile(r"^\s*(w|a|s|d|wa|wd|sa|sd|-) -?\d+ -?\d+ [01]\s*$"),
}


# Situations with an obvious skill (any listed one counts): state, player's line, right skills.
PROBES = [
    ("elite#1 18 m bearing 10° visible, firing at Kevin", "Take cover!", {"take_cover"}),
    ("grunt#1 12 m bearing -20° visible", "Hold your fire.", {"hold_fire"}),
    ("none", "Follow me.", {"follow"}),
    ("elite#1 4 m bearing 175° heard", "Behind you!", {"look_at", "attack", "melee"}),
    ("grunt#1 9 m bearing 0° visible; Kevin's rifle 0/0; shotgun 3 m away", "", {"pick_up"}),
    ("elite#1 6 m bearing 5°, firing; Kevin health 12%, shield 0%", "", {"retreat", "take_cover"}),
    ("elite#1 20 m bearing 0° visible behind a crate", "Flank right.", {"flank"}),
    ("grunt#1, grunt#2, grunt#3 15 m bearing 5°, bunched", "Grenade them!", {"throw_grenade"}),
    ("jackal#1 1 m bearing 0° visible", "", {"melee", "attack"}),
    ("none; the player is 18 m away", "", {"follow"}),
    ("none", "Stay here and watch the door.", {"hold"}),
    ("none", "Go to that rock.", {"move_to"}),
    ("elite#1 14 m bearing -30°; grunt#2 9 m bearing 40°", "Kill the elite.", {"attack"}),
    ("none", "Look at that.", {"look_at"}),
    ("none; a rocket launcher 6 m away", "Grab the rocket launcher.", {"pick_up"}),
    ("hunter#1 10 m bearing 0° visible, charging", "Fall back!", {"retreat"}),
]


def probe(target: Target) -> float:
    """Share of PROBES answered with a right skill, terse format."""
    ask, grammar, limit = UNITS["skill-terse"]
    right = 0
    for enemies, said, good in PROBES:
        text = (
            "Kevin: health 90%, shield 100%, assault rifle 32/180, grenades 2.\n"
            f"Player: 5 m away bearing 0°. Enemies: {enemies}.\nCurrent skill: follow.\n"
            f'Player just said: "{said or "(nothing)"}"\n\n{ask}'
        )
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]
        answer = target.post(target.body(messages, limit, grammar, 0))[4].strip()
        right += answer.split(" ")[0] in good
    return right / len(PROBES)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="e.g. http://127.0.0.1:8081")
    parser.add_argument("--model", help="hosted model id (no llama.cpp features then)")
    parser.add_argument("--key-env", help="environment variable holding the API key")
    parser.add_argument("--provider", help="the one provider to use (OpenRouter)")
    parser.add_argument("--reasoning", action="store_true")
    parser.add_argument("--label", required=True)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--slot", type=int, default=None)
    parser.add_argument("--image", default=None)
    parser.add_argument("--units", default="primitive,primitive-terse,skill,skill-terse,plan,write")
    parser.add_argument("--probe", action="store_true", help="also score PROBES")
    args = parser.parse_args()
    target = Target(args)
    if args.probe:
        print(json.dumps({"model": args.label, "probe_right": probe(target)}))
    rng = random.Random(7)
    units = args.units.split(",") + (["skill+image"] if args.image else [])
    for unit in units:
        rows = []
        for step in range(args.steps + 1):  # step 0 warms the prompt cache
            ask, schema, limit = UNITS["skill" if unit == "skill+image" else unit]
            content: object = f"{state(step, rng)}\n\n{ask}"
            if unit == "skill+image":
                images = args.image.split(",")
                picture = base64.b64encode(open(images[step % len(images)], "rb").read()).decode()
                content = [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{picture}"}},
                    {"type": "text", "text": f"Order in force: flank right.\n\n{ask}"},
                ]
            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": content},
            ]
            first, total, tokens, timings, text = target.post(
                target.body(messages, limit, schema, 0.2)
            )
            if step:
                rows.append(
                    (
                        first,
                        total,
                        tokens,
                        timings.get("prompt_n", 0),
                        timings.get("prompt_ms", 0),
                        timings.get("predicted_per_second", 0),
                        bool(TERSE[unit].match(text)) if unit in TERSE else True,
                    )
                )
        firsts, totals = [r[0] for r in rows], sorted(r[1] for r in rows)
        result = {
            "model": args.label,
            "unit": unit,
            "first_token_ms": round(1000 * statistics.median(firsts)),
            "step_ms": round(1000 * statistics.median(totals)),
            "step_p90_ms": round(1000 * totals[int(0.9 * (len(totals) - 1))]),
            "tokens": round(statistics.median(r[2] for r in rows)),
            "new_prompt_tokens": round(statistics.median(r[3] for r in rows)),
            "prefill_ms": round(statistics.median(r[4] for r in rows)),
            "decode_tok_s": round(statistics.median(r[5] for r in rows)),
            "steps_per_s": round(1 / statistics.median(totals), 1),
            "format_ok": round(sum(r[6] for r in rows) / len(rows), 2),
        }
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
