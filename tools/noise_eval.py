"""Compares ways to tell real player lines from filler and cut-off fragments (docs/findings.md
§9): m8py's punctuation rule against Kev yes/no questions asked with each line's original prompt.

Usage: python tools/noise_eval.py <logs> [--kev http://127.0.0.1:8080/v1/systemone] [--no-kev]

Labels live in tools/noise_labels.py, by position among the player lines of the labelled
sessions (in that order), so the transcripts themselves stay out of the repo.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from noise_labels import LABELS, SESSIONS

from m8py.text import is_noise

QUESTIONS = {
    "speak (current)": "Should Kevin speak now?",
    "answerable": (
        "Did the player just say something Kevin should answer, rather than filler, noise or "
        "a cut-off fragment?"
    ),
    "noise (inverted)": "Is the player's newest line only filler, noise or an unfinished fragment?",
    "makes sense": (
        "Does the player's newest line make sense on its own as something Kevin can reply to?"
    ),
}


def player_turns(logs: Path) -> list[dict]:
    """Each player line with the Kev prompt it was decided with."""
    out = []
    for session in SESSIONS:
        rows = [json.loads(line) for line in (logs / session / "trace.jsonl").open()]
        heard = None
        for row in rows:
            if row["kind"] == "heard":
                heard = row["data"].get("text", "")
            elif row["kind"] == "kev" and heard is not None and row["data"].get("calls"):
                request = row["data"]["calls"][0]["request"]
                out.append({"text": heard, "state": request["state"], "model": request["model"]})
                heard = None
    return out


def report(name: str, scores: list[tuple[float, str]]) -> None:
    real = [p for p, label in scores if label == "R"]
    noise = [p for p, label in scores if label == "N"]
    auc = sum((a > b) + 0.5 * (a == b) for a in real for b in noise) / (len(real) * len(noise))
    print(
        f"{name:18s} AUC {auc:.2f} | at 0.5: real answered {sum(p >= 0.5 for p in real)}/"
        f"{len(real)}, noise dropped {sum(p < 0.5 for p in noise)}/{len(noise)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", type=Path)
    parser.add_argument("--kev", default="http://127.0.0.1:8080/v1/systemone")
    parser.add_argument("--no-kev", action="store_true")
    args = parser.parse_args()
    turns = [(t, LABELS[i]) for i, t in enumerate(player_turns(args.logs)) if i in LABELS]
    report("punctuation rule", [(0.0 if is_noise(t["text"]) else 1.0, label) for t, label in turns])
    if args.no_kev:
        return
    scores: dict[str, list[tuple[float, str]]] = {q: [] for q in QUESTIONS}
    for turn, label in turns:
        questions = {q: {"type": "noul", "instructions": text} for q, text in QUESTIONS.items()}
        request = {"model": turn["model"], "state": turn["state"], "questions": questions}
        body = json.load(
            urllib.request.urlopen(
                urllib.request.Request(
                    args.kev,
                    data=json.dumps(request).encode(),
                    headers={"Content-Type": "application/json"},
                ),
                timeout=30,
            )
        )
        for q in QUESTIONS:
            p = body["answers"][q]["noul"]
            scores[q].append((1 - p if "inverted" in q else p, label))
    for q, s in scores.items():
        report(q, s)


if __name__ == "__main__":
    main()
