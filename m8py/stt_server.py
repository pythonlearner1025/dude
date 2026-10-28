from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

import numpy as np
from aiohttp import web

from .listen import decode_wav, resample


class Recognizer:
    def __init__(self, directory: Path, hotwords: list[str], hotword_score: float) -> None:
        import sherpa_onnx

        options = {}
        if hotwords:
            # Hotwords need beam search and a BPE vocabulary. Parakeet ships only tokens.txt,
            # so score each piece by its id (earlier merges first).
            work = Path(tempfile.mkdtemp(prefix="stt-hotwords-"))
            lines = (directory / "tokens.txt").read_text().splitlines()
            pieces = (line.rsplit(" ", 1) for line in lines)
            (work / "bpe.vocab").write_text("".join(f"{p}\t{-int(i)}\n" for p, i in pieces))
            (work / "hotwords.txt").write_text("".join(f"{word}\n" for word in hotwords))
            options = {
                "decoding_method": "modified_beam_search",
                "max_active_paths": 4,
                "hotwords_file": str(work / "hotwords.txt"),
                "hotwords_score": hotword_score,
                "modeling_unit": "bpe",
                "bpe_vocab": str(work / "bpe.vocab"),
            }
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(directory / "encoder.int8.onnx"),
            decoder=str(directory / "decoder.int8.onnx"),
            joiner=str(directory / "joiner.int8.onnx"),
            tokens=str(directory / "tokens.txt"),
            model_type="nemo_transducer",
            num_threads=4,
            **options,
        )

    def transcribe(self, samples: np.ndarray) -> str:
        stream = self.recognizer.create_stream()
        stream.accept_waveform(16000, samples.tolist())
        self.recognizer.decode_stream(stream)
        return stream.result.text.strip()


def create_app(recognizer: Recognizer) -> web.Application:
    app = web.Application()

    async def health(request):
        return web.json_response({"status": "ok"})

    async def transcribe(request):
        if request.content_type.startswith("multipart/"):
            form = await request.post()
            field = form.get("file")
            data = field.file.read() if hasattr(field, "file") else b""
        else:
            data = await request.read()
        try:
            samples, rate = decode_wav(data)
            samples = resample(samples, rate)
            text = await asyncio.to_thread(recognizer.transcribe, samples)
            return web.json_response({"text": text})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)

    app.router.add_get("/health", health)
    app.router.add_post("/v1/audio/transcriptions", transcribe)
    return app


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("model_dir", type=Path)
    p.add_argument("port", nargs="?", type=int, default=8083)
    p.add_argument("--hotword", action="append", default=[], help="word to bias toward")
    # 1.25 fixed 8 of 13 misheard "Kevin"s in 647 playtest clips; 1.5+ turned "Cover." into "Kevin."
    p.add_argument("--hotword-score", type=float, default=1.25)
    args = p.parse_args()
    recognizer = Recognizer(args.model_dir, args.hotword, args.hotword_score)
    web.run_app(create_app(recognizer), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
