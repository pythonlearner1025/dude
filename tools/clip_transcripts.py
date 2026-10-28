"""Lists every saved mic clip with the transcript m8py heard for it, as '<wav>\t<text>' lines.

Usage: python tools/clip_transcripts.py <logs> > clips.tsv
"""

from __future__ import annotations

import bisect
import json
import sys
from pathlib import Path


def main() -> None:
    for session in sorted(Path(sys.argv[1]).iterdir()):
        audio, trace = session / "audio", session / "trace.jsonl"
        if not audio.is_dir() or not trace.exists():
            continue
        clips = sorted((int(p.name.split("-")[0]), p) for p in audio.glob("*-mic-mic.wav"))
        stamps = [stamp for stamp, _ in clips]
        for line in trace.read_text().splitlines():
            row = json.loads(line)
            if row["kind"] != "heard":
                continue
            # a clip is named when its transcript arrives, just before the heard entry
            i = bisect.bisect_right(stamps, row["t"] + 50) - 1
            if i >= 0 and row["t"] - stamps[i] < 3000:
                print(f"{clips[i][1]}\t{row['data'].get('text', '')}")


if __name__ == "__main__":
    main()
