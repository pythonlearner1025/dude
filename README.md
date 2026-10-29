# dude

**Kevin**: an AI teammate who talks and fights beside you in Halo CE. A Python port of
[chasmlol/m8](https://github.com/chasmlol/m8). You play in a browser; Kevin's voice and memory
run locally on one RTX 3090 Ti, and LLMs do all of his playing through skills written in code.

```mermaid
flowchart LR
    you(["you speak"]) --> stt["STT<br/>Parakeet"] --> voice["Voice<br/>Gemma-12B"] -- speech --> game(["Halo"])
    stt --> actor["Actor<br/>DeepSeek V4.1 Flash, ~0.2 s"] -- "a skill" --> skills["Skills<br/>Python, each game state"] -- actions --> game
    game -- state --> skills
    skills -- "trace: everything, + frames" -.-> coach["Coach<br/>Opus in Claude Code,<br/>looks every minute"] -- "new, fixed skills" --> skills
```

- **Voice** answers what you say (not filler like "uh"); first words ~1.9 s after you stop.
- **The actor** picks Kevin's next skill ("flank grunt#31 right") whenever something happens.
- **Skills** are short Python generators in `kevin-skills/` that drive Halo's own AI.
- **The coach** watches: about once a minute it reads everything since its last look (your
  words, Kevin's, his decisions, skills, state and your view) and fixes what went wrong. Nothing
  sends it requests.

Design and numbers: [the skill loop](docs/design/kevin-skill-loop.html),
[the coach loop](docs/design/kevin-coach-loop.html), [findings §12](docs/findings.md).

## Run

```bash
# b650s, in ~/m8work/scripts: models, m8py in skill mode, the coach (Claude Code signed in)
./start-stack-skills.sh && M8PY_CONFIG=configs/b650s-skills.toml ./restart-m8py.sh && ./start-coach.sh
# Mac: serve the game, open http://localhost:8000/?m8=ws://100.126.232.8:8091/game, New Game
cd ~/halo-m8-web && python3 web_serve.py
```

Older modes: Kev-4B picking scripted actions (`configs/b650s.toml`) and co-op with Open-P2P
playing Kevin (`configs/b650s-coop.toml`). `m8py/` the companion · `kevin-skills/` the seed skill
library · `games/halo/` the game patch · `tools/` benchmarks and log tools · `infra/b650s/`
launch scripts · `docs/` findings and design. Each run logs to `logs/<session>/`.
