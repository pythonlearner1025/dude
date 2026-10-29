# b650s scripts

Launch scripts for the model servers, the streaming desktop and the game on b650s (RTX 3090 Ti).
They live in `~/m8work/scripts/` there and assume that layout (`~/m8work/{llama.cpp,models,
breeze-tts,halo,dude,logs,run}`); see `docs/reports/model-servers.md` and
`docs/reports/streaming-setup.md` for how each piece was installed.

Two stacks fit (see `docs/findings.md` §1 and §6): `./start-stack-gemma.sh` (m8's Gemma4-12B with
Kev Q4_K_M, 22.1 GB) and `./start-stack-qwen.sh` (Qwen3.5-9B with Kev Q8, 21.9 GB). By hand:

```bash
KEV_CTX=4096 KEV_EXTRA="-np 1" ./start-kev.sh   # Kev-4B Q8_0 on :8080 (/v1/systemone)
CHAT_EXTRA="-np 2 -kvu" ./start-chat-qwen.sh          # Qwen3.5-9B + mmproj on :8081
./start-breeze.sh                                # Breeze TTS 2 on :7860 (m8's fast flags)
./start-stt.sh                                   # Parakeet via m8py.stt_server on :8083 (CPU)
./vram.sh                                        # per-process VRAM, labelled by port
./stop-all.sh                                    # stops only the model servers above
```

**Skill mode** (the current one; `docs/design/kevin-skill-loop.html`): `./start-stack-skills.sh`
(Gemma, Breeze, STT, ~18 GB), `M8PY_CONFIG=configs/b650s-skills.toml ./restart-m8py.sh`, and
`./start-coach.sh`. The actor is DeepSeek V4.1 Flash on OpenRouter; its key is
`~/m8work/notes/openrouter.env` (mode 600), which `start-m8py.sh` loads. Skills live in the git repo
`~/m8work/kevin-skills` (seeded from `dude/kevin-skills`). The coach watches the newest session
in `dude/logs` and, at most once a minute when something happened in a game, writes a packet to
`~/m8work/run/observations/<session>/<n>/` (`packet.md`, `packet.json`, `frames/`) and runs
`claude -p` on it in the library (Opus 5.5, medium effort; `COACH_MODEL`, `COACH_EFFORT`), which
leaves `claude.log` (stream-json: `python3 ~/m8work/dude/tools/coach_log.py <dir>/claude.log`)
and `result.md` there. It uses the current Claude Code in `~/.npm-global/bin` (the one in
`/usr/local` is 2.0.1), signed in with a one-year token from `claude setup-token` kept in
`~/m8work/notes/claude-coach.env` (mode 600), which `start-coach.sh` loads, and runs apart from
this machine's personal Claude Code setup (project settings only, the personal CLAUDE.md excluded,
no skills or MCP, six tools): see `ISOLATED` in `m8py/coach.py`. `tools/coach_bench.py` re-runs a
packet with another model or effort on a clone of the library.
`HALO_START_LEVEL=a30 ./halo` plays a campaign level at once, for tests without the menus.

**Co-op mode** (Kevin is player 2, played by Open-P2P; no Kev): `./start-stack-coop.sh` (Gemma,
Breeze, STT and `start-p2p.sh`, Open-P2P 600M, ~21.3 GB) then
`M8PY_CONFIG=configs/b650s-coop.toml ./restart-m8py.sh`. The host's invite makes m8py run
`kevin-coop.sh`: Kevin's own Halo (`kevin-client.sh`) plus the Open-P2P client
(`dude/tools/p2p/client.py`); logs in `logs/{kevin-client,p2p-server,p2p-client}.log`.
`dude/tools/p2p/open-p2p.patch` is our change to the Open-P2P checkout.

`start-chat.sh` (Gemma4-12B) is m8's original LLM; it fits next to Breeze only with Kev at Q4_K_M,
which is what `start-stack-gemma.sh` runs (the stack in use).
`restart-m8py.sh` restarts m8py on the current checkout (under a systemd user unit, so it survives
the ssh session); `restart-stt.sh` restarts the STT server.
`start-desktop.sh` / `stop-desktop.sh` run Xorg + Openbox + PulseAudio null sink + Sunshine for
Moonlight streaming; `run-halo.sh` is Sunshine's "Halo m8" app.
