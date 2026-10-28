from __future__ import annotations

import argparse
import asyncio
import difflib
import re
import tempfile
from pathlib import Path

import numpy as np
from aiohttp import web

from .listen import decode_wav, resample


def keep_hotword(plain: str, biased: str, word: str) -> str:
    """Take only the hotword from the biased transcript: where it swaps one plain word for it."""
    a, b = plain.split(), biased.split()

    def key(token: str) -> str:
        return re.sub(r"\W+", "", token).lower()

    out = list(a)
    matcher = difflib.SequenceMatcher(a=[key(t) for t in a], b=[key(t) for t in b], autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "replace" and i2 - i1 == 1 and j2 - j1 == 1:
            if re.fullmatch(rf"{re.escape(word)}\W*", b[j1]):
                out[i1] = re.sub(r"[\w']+", word, a[i1], count=1)
    return " ".join(out)


class Recognizer:
    def __init__(self, directory: Path, hotwords: list[str], hotword_score: float) -> None:
        import sherpa_onnx

        def load(**options) -> sherpa_onnx.OfflineRecognizer:
            return sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(directory / "encoder.int8.onnx"),
                decoder=str(directory / "decoder.int8.onnx"),
                joiner=str(directory / "joiner.int8.onnx"),
                tokens=str(directory / "tokens.txt"),
                model_type="nemo_transducer",
                num_threads=4,
                **options,
            )

        self.hotwords = hotwords
        self.plain = load()
        self.biased = None
        if hotwords:
            # Hotwords need beam search and a BPE vocabulary. Parakeet ships only tokens.txt,
            # so score each piece by its id (earlier merges first). Beam search also drops or
            # swaps short words on this model ("Cover." -> "Okay."), so the greedy pass stays the
            # transcript and the biased pass only supplies one-word swaps to a hotword.
            work = Path(tempfile.mkdtemp(prefix="stt-hotwords-"))
            lines = (directory / "tokens.txt").read_text().splitlines()
            pieces = (line.rsplit(" ", 1) for line in lines)
            (work / "bpe.vocab").write_text("".join(f"{p}\t{-int(i)}\n" for p, i in pieces))
            (work / "hotwords.txt").write_text("".join(f"{word}\n" for word in hotwords))
            self.biased = load(
                decoding_method="modified_beam_search",
                max_active_paths=4,
                hotwords_file=str(work / "hotwords.txt"),
                hotwords_score=hotword_score,
                modeling_unit="bpe",
                bpe_vocab=str(work / "bpe.vocab"),
            )

    @staticmethod
    def decode(recognizer, samples: np.ndarray) -> str:
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, samples.tolist())
        recognizer.decode_stream(stream)
        return stream.result.text.strip()

    async def transcribe(self, samples: np.ndarray) -> str:
        if self.biased is None:
            return await asyncio.to_thread(self.decode, self.plain, samples)
        plain, biased = await asyncio.gather(
            asyncio.to_thread(self.decode, self.plain, samples),
            asyncio.to_thread(self.decode, self.biased, samples),
        )
        for word in self.hotwords:
            plain = keep_hotword(plain, biased, word)
        return plain


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
            text = await recognizer.transcribe(samples)
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
    # Over 647 playtest clips, 1.25 fixed 12 misheard "Kevin"s and changed 2 other words;
    # 2.0 also turned "Okay." and "Cover." into "Kevin."
    p.add_argument("--hotword-score", type=float, default=1.25)
    args = p.parse_args()
    recognizer = Recognizer(args.model_dir, args.hotword, args.hotword_score)
    web.run_app(create_app(recognizer), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
