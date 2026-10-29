# Kevin's body API (`k`), single-player companion

The game sends Kevin's state twice a second; each skill gets one step (until its next `yield`)
per state. Positions are metres `[x, y, z]`; `facing` is degrees counter-clockwise from +x;
health and shields run from 0 to 1. The implementation is `m8py/body.py` in the dude repo.

## Reading

| | |
|---|---|
| `k.time` | seconds (monotonic), for time limits |
| `k.me` | `{"pos", "facing", "health", "shields", "activity", "target", "vehicle"}`; activity is following, holding, cover, ... |
| `k.player` | `{"pos", "facing", "health", "shields", "aim": {"pos", "label", "distance_m"}, "vehicle"}` |
| `k.enemies` | `[{"id", "kind", "health", "pos", "distance_m", "in_sight"}]`, distance from Kevin |
| `k.enemy(target)`, `k.alive(target)` | an enemy by `kind#id` or id; whether it is still there |
| `k.nearest_enemy(in_sight=True)` | the nearest enemy (in sight only, by default) or None |
| `k.offered(name)` | an action the game offers now, e.g. `k.offered("pick_up")["options"]` (id → label) |
| `k.direction(pos)` | "ahead", "behind", "to the left", "to the right" of the player |
| `k.state` | the whole state message, including the game's own text summary |

## Geometry

`k.distance(a, b)` (on the ground), `k.ahead_of(pos, facing, metres)`,
`k.side_point(target, origin, side, metres)` (left or right of the line origin → target, as seen
from origin), `k.behind(point, away_from, metres)` (past point, on the far side from away_from),
`k.stuck(seconds=3)` (short of the last `k.go` point and no closer for that long).

## Acting

Commands are sent after the step; the same command again is dropped, so call them every step.

| | |
|---|---|
| `k.go(point)` | walk to a point and hold there (within ~1.2 m); resent only if it moves 1 m |
| `k.follow()`, `k.stay()` | follow the player; hold where he stands |
| `k.shoot(target)`, `k.rush(target)` | shoot at; charge |
| `k.hold_fire()` | stop shooting (until a shoot or rush) |
| `k.cover()`, `k.fall_back()` | the game's own cover-finding and retreat |
| `k.crouch(on=True)`, `k.jump()` | |
| `k.melee(target)`, `k.grenade(target, kind="frag")` | kind: frag or plasma |
| `k.pick_up(id)`, `k.switch_weapon()` | an id from `k.offered("pick_up")` |
| `k.do(action, option=None)` | any other companion action the state offers |
| `yield from k.run(name, **args)` | run another skill's steps; returns its Done or Failed |

A skill ends by returning `Done(reason)` or `Failed(reason)` (from `m8py.skills`); the reason is
read by the actor, so say what happened in a few words.
