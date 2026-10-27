#!/usr/bin/env python3
"""Standalone remote-mic client: sounddevice + numpy + websockets only."""

from __future__ import annotations

import argparse
import asyncio
import json
import queue

import numpy as np
import sounddevice as sd
import websockets

RATE, FRAME = 16000, 320


def resample(samples: np.ndarray, source: int) -> np.ndarray:
    if source == RATE:
        return samples
    n = round(len(samples) * RATE / source)
    return np.interp(np.arange(n) * source / RATE, np.arange(len(samples)), samples).astype(
        np.float32
    )


async def stream(args) -> None:
    device = sd.query_devices(args.device, "input")
    source = int(device["default_samplerate"])
    q: queue.Queue[np.ndarray] = queue.Queue()

    def callback(indata, frames, timing, status):
        q.put(np.asarray(indata).mean(axis=1).copy())

    pending = np.empty(0, np.float32)
    with sd.InputStream(
        device=args.device,
        channels=int(device["max_input_channels"]),
        samplerate=source,
        callback=callback,
    ):
        while True:
            try:
                async with websockets.connect(args.url) as ws:
                    await ws.send(
                        json.dumps(
                            {
                                "type": "hello",
                                "sample_rate": RATE,
                                "format": "s16le",
                                "frame_ms": 20,
                            }
                        )
                    )
                    print(f"connected to {args.url}")
                    while True:
                        chunk = await asyncio.to_thread(q.get)
                        pending = np.concatenate((pending, resample(chunk, source)))
                        while len(pending) >= FRAME:
                            frame, pending = pending[:FRAME], pending[FRAME:]
                            rms = float(np.sqrt(np.mean(frame * frame)))
                            bar = "#" * min(40, int(rms * 200))
                            print(
                                f"\rlevel {20 * np.log10(max(rms, 1e-5)):6.1f} dB {bar:<40}",
                                end="",
                                flush=True,
                            )
                            await ws.send((np.clip(frame, -1, 1) * 32767).astype("<i2").tobytes())
            except Exception as exc:
                print(f"\ndisconnected: {exc}; reconnecting ...")
                await asyncio.sleep(1)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--list", action="store_true")
    p.add_argument("--device")
    p.add_argument("--url", default="ws://127.0.0.1:8091/mic")
    args = p.parse_args()
    if args.list:
        print(sd.query_devices())
        return
    asyncio.run(stream(args))


if __name__ == "__main__":
    main()
