"""Re-transcribes recorded mic clips plain and with the mate's name boosted, as the STT server
does, and prints every clip whose transcript changes (docs/findings.md §9).

Usage: python tools/stt_hotword_eval.py <parakeet model dir> clips.tsv [--score 1.25] [--limit N]
(clips.tsv from tools/clip_transcripts.py)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from m8py.listen import decode_wav, resample
from m8py.stt_server import Recognizer, keep_hotword


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("clips", type=Path)
    parser.add_argument("--hotword", default="Kevin")
    parser.add_argument("--score", type=float, default=1.25)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    clips = [line.split("\t")[0] for line in args.clips.read_text().splitlines()][: args.limit]
    recognizer = Recognizer(args.model_dir, [args.hotword], args.score)
    changed, plain_ms, biased_ms = [], [], []
    for clip in clips:
        samples = resample(*decode_wav(Path(clip).read_bytes()))
        started = time.monotonic()
        plain = recognizer.decode(recognizer.plain, samples)
        plain_ms.append((time.monotonic() - started) * 1000)
        started = time.monotonic()
        biased = recognizer.decode(recognizer.biased, samples)
        biased_ms.append((time.monotonic() - started) * 1000)
        kept = keep_hotword(plain, biased, args.hotword)
        if kept != plain:
            changed.append((plain, kept))
    plain_ms.sort()
    biased_ms.sort()
    print(
        f"{len(changed)} of {len(clips)} clips changed at score {args.score}; decode p50 plain "
        f"{plain_ms[len(plain_ms) // 2]:.0f} ms, biased {biased_ms[len(biased_ms) // 2]:.0f} ms"
    )
    for plain, kept in changed:
        print(f"  {plain!r} -> {kept!r}")


if __name__ == "__main__":
    main()
