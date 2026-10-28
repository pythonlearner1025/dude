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
