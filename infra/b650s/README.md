# b650s scripts

Launch scripts for the model servers, the streaming desktop and the game on b650s (RTX 3090 Ti).
They live in `~/m8work/scripts/` there and assume that layout (`~/m8work/{llama.cpp,models,
breeze-tts,halo,dude,logs,run}`); see `docs/reports/model-servers.md` and
`docs/reports/streaming-setup.md` for how each piece was installed.

Fitted stack (21.6 GB of 23 GB, see `docs/findings.md`):

```bash
KEV_CTX=4096 KEV_EXTRA="-np 1" ./start-kev.sh   # Kev-4B Q8_0 on :8080 (/v1/systemone)
CHAT_EXTRA="-np 2" ./start-chat-qwen.sh          # Qwen3.5-9B + mmproj on :8081
./start-breeze.sh                                # Breeze TTS 2 on :7860 (m8's fast flags)
./start-stt.sh                                   # Parakeet via m8py.stt_server on :8083 (CPU)
./vram.sh                                        # per-process VRAM, labelled by port
./stop-all.sh                                    # stops only the model servers above
```

`start-chat.sh` (Gemma4-12B) is m8's original LLM; it does not fit next to Breeze on 24 GB.
`start-desktop.sh` / `stop-desktop.sh` run Xorg + Openbox + PulseAudio null sink + Sunshine for
Moonlight streaming; `run-halo.sh` is Sunshine's "Halo m8" app.
