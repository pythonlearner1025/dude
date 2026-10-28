# Halo: Combat Evolved (OpenCE) with m8py

The game side comes from [OpenCE](https://github.com/OpenCommunityEdition/OpenCE) at commit
`8102e711` plus m8's patch ([chasmlol/m8](https://github.com/chasmlol/m8) `games/halo/m8.patch`).
Game data (the Xbox `maps/`) is never included: it comes from your own disc.

- **Native Linux** (b650s): m8's patch builds unchanged (`python3 configure.py --release
  --portable --linux-cc clang-22; ninja linux`); the game connects to m8py on TCP
  `127.0.0.1:47800`. See `docs/reports/halo-linux-build.md`.
- **Browser** (played on the Mac from `http://localhost:8000`): `opence-m8-web.patch` (on top of
  m8's patch) carries the companion link over a WebSocket to m8py's `/game`, and adds an in-page
  microphone streamer to `/mic`. Build with `ninja web` (Emscripten 6.0.10). See
  `docs/reports/halo-web-build.md`.

Playing in the browser on the Mac:

```bash
cd ~/halo-m8-web && python3 web_serve.py
```

with your own extracted `maps/` folder beside `web_serve.py` (it writes `maps/manifest.json` at
startup), then open `http://localhost:8000/?m8=ws://100.126.232.8:8091/game`. The page imports the
maps into the browser's storage by itself on the first visit (`?autoload=0` turns that off; see
`docs/reports/halo-web-autoload.md`); turn the microphone on once, then Play. Only one game should be open
at a time: the newest connection takes over the companion.

The browser launcher lists the ten campaign levels; a click starts that level straight into
gameplay. Opening cinematics are skipped through the engine's own skip wherever the level script
allows it (`?set=HALO_SKIP_CINEMATICS=0` restores them), and a fresh level start sends m8py a
`new_game` message that clears the mate's memory and stored checkpoint memories
(`docs/reports/halo-levels-skip-reset.md`). `?perf=1` logs the game's frame times to the browser
console (`docs/reports/halo-web-perf.md`).

The companion state (patch at OpenCE `4a5975b6`) carries structured fields beside the prose:
`kevin{pos, facing, activity, target, vehicle}`, `player{pos, facing, aim, vehicle}`,
`kevin_from_player{distance_m, bearing_deg}` and `enemies[]`, plus player-relative sentences
("Kevin is 5 m behind you"). m8py's validator reads them to tell whether an action finished.
