# Kevin's skill library: instructions for the coach

You maintain the skills that play Kevin, the player's Marine teammate in Halo CE (single player).
A fast model (the actor, DeepSeek V4.1 Flash) picks one skill at a time from a catalog built
from this library, whenever something happens (the player speaks, a skill ends, an enemy shows
up) and every few seconds in combat. m8py runs the picked skill one step per game state, twice a
second, and Halo's own AI walks, aims and fires to carry out each step's commands.

You are started with one ticket (a JSON file; its path is in your prompt). Resolve it, test,
commit, write the result, and stop.

## What you may change
- `skills/*.py`: the skills.
- `actor/prompt.md`: rules and worked examples the actor reads after the catalog.
- `tests/`: scenario tests.
Never change anything outside this directory (the runtime, `m8py/`, is not yours).

## The skill contract
- A skill is a generator function decorated with
  `@skill(when=..., args={...}, tags=(...))` from `m8py.skills`. Its first parameter is the
  body `k` (see `body/API.md`); the rest are its arguments, given by the actor in order.
- Each step reads `k` and issues commands; `yield` ends the step. Call commands every step: the
  body drops repeats. Never sleep, block, do I/O, or keep state outside the generator.
- End with `return Done(reason)` or `return Failed(reason)`. The actor reads the reason, so say
  what happened in a few words ("low health", "target down", "path blocked"). A skill that
  never returns (follow, stay, cover the player) runs until the actor picks another.
- Bound every skill that ends: a time limit, `k.stuck(...)`, a lost target, Kevin's health below
  25% (return `Failed("low health")`; the actor then picks cover or a retreat). Where a cheap
  fallback exists (another side, a shorter distance), try it before failing.
- Compose with `result = yield from k.run("attack", target=...)` instead of copying code. Keep
  skills under 60 lines.
- Tags pick when the actor sees a skill: `core` always, `combat` when enemies are known, `calm`
  when none are. The actor sees at most 20 skills, core first, so keep the library small: extend
  or parameterise a skill before adding a near-duplicate, and delete what nothing uses.
- `when` is all the actor knows about a skill. Write it for a fast model choosing in 200 ms:
  what it does, then the player's phrases for it in quotes. One line, under 140 characters,
  distinct from every other skill's.

## Tickets
- `new_order`: the actor answered `nofit` for an order no skill covers. Write or extend a skill
  and add the player's phrasing to the examples in `actor/prompt.md`.
- `failure`: a skill raised an error, or failed twice within three minutes. Find the cause in the
  session trace (`trace` in the ticket; read the `decision`, `skill`, `body` and `event` lines
  around the failure, not the whole file), fix it, and add a test that would have caught it.
- `correction`: the player told Kevin he got something wrong. Fix whichever caused it: the
  skill, its tags, or the actor's rules and examples.
- `review`: every ten minutes of play. Read the session's `decision` lines: where the actor
  picked badly, add a rule or an example to `actor/prompt.md`; where it answered `nofit`, check
  the matching ticket was handled.
- `library_errors` in any ticket lists files that failed to load: fix them first.

## Before you finish
1. `PYTHONPATH=/home/minjune/m8work/dude /home/minjune/m8work/dude/.venv/bin/python -m m8py.skilltest .`
   must print `ok`. It loads every skill, checks the `when` lines, runs each skill through
   calm, combat, dying-target and blocked situations, and runs `tests/`.
2. `git add -A && git commit -m "<what changed> (<ticket id>)"`. m8py loads the new skills the
   next time no skill is running.
3. Write `<ticket path without .json>.result.md`: two or three sentences for the session log,
   saying what you changed and what Kevin will now do.
