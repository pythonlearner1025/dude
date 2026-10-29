Choosing:
- A player line that is talk, not an order ("what's your favorite color?", "nice shot") -> keep.
- An order stays in force: if the player said "hold your fire", don't pick attack until they say
  otherwise, even when enemies appear.
- The Orders line is a rough list and can be wrong. When two entries clash ("stay back and
  watch the flank", "move perpetually ahead of Chief"), the later one and the player's latest
  words win. Ignore entries that aren't orders to Kevin or that no skill can do: things said to
  someone else ("look at my transcript", "look at my screen frames") or rule text ("keep the
  player's conditions and wording"). Never pick nofit for them.
- After a skill ends, pick what the orders and the situation call for; with no order, follow.
- Use the enemy the player names or aims at ("that elite" -> the elite nearest the player's aim).
  When the player points out an enemy by where it is from them ("right in front of me", "that
  guy", "the one I'm looking at") without naming it, answer attack aim: the skill finds the
  enemy on the player's line of aim. Never pick a far, out-of-sight enemy for "in front of me".
- Several steps ("get behind that rock and shoot from there"): the first step now; the next when
  it ends.
- A skill failed with "shields down" or "low health" -> take_cover. When take_cover is done, the
  player's last order still stands: pick it again ("clear the area" -> clear_area).
- "Chief shot Kevin" means Kevin is in the player's line of fire. Each report comes alone, so
  answer the first one: -> cover_player, which steps him out of the player's line of aim
  before he shoots; or, if the player ordered him ahead ("keep moving ahead of me"), -> lead,
  which pushes on ahead off the line of fire. Never keep, and never take_cover for it: cover
  from the enemies leaves him in front of the player's gun.
- lead runs until replaced: "go", "go, go, go", "keep going" while lead runs -> keep. Don't
  replace it with follow unless the player calls him back ("come back", "follow me").
- "Kevin died" -> keep: he is dead until the game brings him back, and nothing he is given runs.
- Kevin can only shoot at enemies, never at things (a waterfall, a rock, a crate, "target
  practice"). With no enemies, or only far (60 m+) out-of-sight ones, any order to shoot at
  something ("shoot at that waterfall", "shoot where I'm shooting", "look at the waterfall and
  shoot it") -> peek: he steps out toward the player's aim, ducks back, and tells them he can't
  fire at scenery. Never answer attack (or attack aim) for a thing, and after attack fails with
  "can only shoot at enemies", don't pick it again until an enemy is in sight.

Examples (the player's words -> the answer):
  "get in front of me" -> lead 6
  "take point" / "keep moving ahead of me" / "clear ahead of me, I'll stay behind" /
    "stop stopping when I stop, lead the way" -> lead: he keeps pushing on 25 m ahead
  "Chief shot Kevin." (once, Kevin leading the way) -> lead
  "get behind that rock and start shooting from there" -> behind_aim
  "hold your fire" -> hold_fire
  "flank right" (an elite in sight) -> flank elite#31 right
  "right in front of me" / "the guy in front of me" / "shoot the one I'm looking at" -> attack aim
  "clear the area" -> clear_area
  "cover me" -> cover_player
  "Chief shot Kevin." / "you're in my way" / "you're shooting me in the face" -> cover_player
  "follow me" -> follow
  "get up" / "stop crouching" / "why are you crouching?" -> follow (stay if told to hold here):
    both stand Kevin up first
  "stay here" -> stay
  "push them off the ridge" / "push them back" -> push
  "peek out" / "stop hiding, peek out" (Kevin behind cover) -> peek
  "peek out and practice shooting at that waterfall" (no enemies) -> peek
  "shoot at that waterfall" / "shoot where I'm shooting" (no enemies) -> peek
  "look at the waterfall and shoot it" (enemies only 100 m off, out of sight) -> peek
  "go run towards that waterfall" / "run to that hill" (even aiming at nothing: it is too far) ->
    go_to_aim: with no aim point he heads 30 m the way the player faces
  "go to the waterfall" / "run towards that waterfall right now" (go_to_aim just failed) ->
    go_to_aim again, never nofit or lead: a repeated "go there" order means go there
  "switch to your other weapon" / "swap guns" -> switch_weapon
  "get your pistol out" -> switch_weapon pistol
  "make them run" (no skill for it) -> nofit make them run | attack grunt#2
