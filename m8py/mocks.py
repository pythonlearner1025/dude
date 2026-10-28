from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import struct

from aiohttp import web


def model_app(kind: str, latency: float = 0.02, token_delay: float = 0.005) -> web.Application:
    app = web.Application()

    async def health(request):
        return web.json_response({"status": "ok"})

    async def systemone(request):
        body = await request.json()
        await asyncio.sleep(latency)
        answers = {}
        for key, q in body.get("questions", {}).items():
            if q.get("type") == "noul":
                answers[key] = {"noul": 0.8}
            else:
                choices = list(q.get("criteria", {}))
                choice = next(
                    (x for x in choices if x != "nothing"), choices[0] if choices else "nothing"
                )
                answers[key] = {
                    "choice": choice,
                    "probabilities": {
                        x: (0.9 if x == choice else 0.1 / max(1, len(choices) - 1)) for x in choices
                    },
                    "confidence": 0.9,
                }
        return web.json_response(
            {
                "answers": answers,
                "timings": {
                    "prompt_n": len(str(body.get("state", ""))) // 4,
                    "predicted_n": 1,
                    "prompt_ms": latency * 500,
                    "predicted_ms": latency * 500,
                    "cache_n": 0,
                },
                "usage": {
                    "prompt_tokens": len(str(body.get("state", ""))) // 4,
                    "completion_tokens": 1,
                },
            }
        )

    async def chat(request):
        body = await request.json()
        await asyncio.sleep(latency)
        if body.get("response_format"):
            schema = body["response_format"].get("json_schema", {}).get("schema", {})
            properties = schema.get("properties", {})
            if "orders" in properties:
                content = json.dumps(
                    {"orders": ["Follow the player's latest command"], "remember": []}
                )
            else:
                enum = properties.get("spot", {}).get("enum", [0])
                content = json.dumps({"place": "the marked ground", "spot": enum[-1]})
        elif not body.get("stream", False):
            content = "Kevin remembered the important events and the people involved."
        else:
            content = "[dry and confident] Copy that. Moving now."
        if not body.get("stream", False):
            return web.json_response(
                {
                    "model": "mock-llm",
                    "choices": [{"message": {"content": content}}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10},
                    "timings": {
                        "prompt_n": 20,
                        "predicted_n": 10,
                        "prompt_ms": 10,
                        "predicted_ms": 20,
                        "cache_n": 0,
                    },
                }
            )
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for token in [content[i : i + 5] for i in range(0, len(content), 5)]:
            chunk = {"model": "mock-llm", "choices": [{"delta": {"content": token}}]}
            await response.write(f"data: {json.dumps(chunk)}\n\n".encode())
            await asyncio.sleep(token_delay)
        final = {
            "choices": [{"delta": {}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            "timings": {
                "prompt_n": 20,
                "predicted_n": 10,
                "prompt_ms": 10,
                "predicted_ms": 20,
                "cache_n": 0,
            },
        }
        await response.write(f"data: {json.dumps(final)}\n\n".encode())
        await response.write(b"data: [DONE]\n\n")
        return response

    app.router.add_get("/health", health)
    if kind == "kev":
        app.router.add_post("/v1/systemone", systemone)
    else:
        app.router.add_post("/v1/chat/completions", chat)
    return app


def tts_app(latency: float = 0.02, sample_rate: int = 24000) -> web.Application:
    app = web.Application()

    async def health(request):
        return web.json_response({"status": "ok", "sample_rate": sample_rate})

    async def speech(request):
        await request.post()
        await asyncio.sleep(latency)
        response = web.StreamResponse(headers={"Content-Type": "application/octet-stream"})
        await response.prepare(request)
        samples = sample_rate // 4
        for start in range(0, samples, 1200):
            pcm = b"".join(
                struct.pack("<h", int(1500 * math.sin(2 * math.pi * 220 * i / sample_rate)))
                for i in range(start, min(start + 1200, samples))
            )
            await response.write(pcm)
            await asyncio.sleep(0.003)
        return response

    app.router.add_get("/health", health)
    app.router.add_post("/v1/audio/speech", speech)
    return app


def stt_app(latency: float = 0.02) -> web.Application:
    app = web.Application()

    async def health(request):
        return web.json_response({"status": "ok"})

    async def transcription(request):
        await request.read()
        await asyncio.sleep(latency)
        return web.json_response({"text": "mock transcription"})

    app.router.add_get("/health", health)
    app.router.add_post("/v1/audio/transcriptions", transcription)
    return app


async def serve(args) -> None:
    runners = []
    for app, port in (
        (model_app("kev", args.latency, args.token_delay), args.kev_port),
        (model_app("llm", args.latency, args.token_delay), args.llm_port),
        (tts_app(args.latency), args.tts_port),
        (stt_app(args.latency), args.stt_port),
    ):
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, args.bind, port).start()
        runners.append(runner)
    services = f"Kev {args.kev_port}, LLM {args.llm_port}, TTS {args.tts_port}, STT {args.stt_port}"
    print(f"m8py mocks ready: {services}", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        for runner in runners:
            await runner.cleanup()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--bind", default="127.0.0.1")
    p.add_argument("--kev-port", type=int, default=8080)
    p.add_argument("--llm-port", type=int, default=8081)
    p.add_argument("--tts-port", type=int, default=7860)
    p.add_argument("--stt-port", type=int, default=8083)
    p.add_argument("--latency", type=float, default=float(os.getenv("M8PY_MOCK_LATENCY", "0.02")))
    p.add_argument(
        "--token-delay", type=float, default=float(os.getenv("M8PY_MOCK_TOKEN_DELAY", "0.005"))
    )
    try:
        asyncio.run(serve(p.parse_args()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
