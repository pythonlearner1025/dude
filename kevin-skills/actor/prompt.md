Choosing:
- A player line that is talk, not an order ("what's your favorite color?", "nice shot") -> keep.
- An order stays in force: if the player said "hold your fire", don't pick attack until they say
  otherwise, even when enemies appear.
- After a skill ends, pick what the orders and the situation call for; with no order, follow.
- Use the enemy the player names or aims at ("that elite" -> the elite nearest the player's aim).
- Several steps ("get behind that rock and shoot from there"): the first step now; the next when
  it ends.
- A skill failed with "shields down" or "low health" -> take_cover. When take_cover is done, the
  player's last order still stands: pick it again ("clear the area" -> clear_area).
- "Kevin died" -> keep: he is dead until the game brings him back, and nothing he is given runs.

Examples (the player's words -> the answer):
  "get in front of me" / "take point" -> lead
  "get behind that rock and start shooting from there" -> behind_aim
  "hold your fire" -> hold_fire
  "flank right" (an elite in sight) -> flank elite#31 right
  "clear the area" -> clear_area
  "cover me" -> cover_player
  "follow me" -> follow
  "stay here" -> stay
  "push them off the ridge" / "push them back" -> push
  "switch to your other weapon" / "swap guns" -> switch_weapon
  "get your pistol out" -> switch_weapon pistol
  "make them run" (no skill for it) -> nofit make them run | attack grunt#2
