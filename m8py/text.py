from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

SOUNDS = {
    **{
        x: "(laugh)"
        for x in (
            "laugh",
            "laughs",
            "laughing",
            "laughter",
            "chuckle",
            "chuckles",
            "chuckling",
            "giggles",
            "snickers",
            "cackles",
        )
    },
    **{x: "(sigh)" for x in ("sigh", "sighs", "sighing")},
    **{x: "(cough)" for x in ("cough", "coughs", "coughing")},
    **{x: "(clears throat)" for x in ("clears throat", "clears his throat", "clearing throat")},
}


def clean(text: str) -> str:
    depth = 0
    out: list[str] = []
    i = 0
    while i < len(text):
        c = text[i]
        if depth == 0 and c == "(":
            end = text.find(")", i + 1)
            if end >= 0 and (sound := SOUNDS.get(text[i + 1 : end].strip().lower())):
                out.append(sound)
                i = end + 1
                continue
        if c in "[(":
            depth += 1
        elif c in "])":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(c)
        i += 1
    filtered = "".join(
        c
        for c in out
        if c not in "*_#~`" and not ("\U0001f000" <= c <= "\U0001faff" or "\u2600" <= c <= "\u27bf")
    )
    collapsed = " ".join(filtered.split())
    trimmed = collapsed.strip('"“”').strip()
    return trimmed if any(c.isalnum() for c in trimmed) else ""


class PieceKind(Enum):
    TEXT = "text"
    NOTE = "note"


@dataclass(frozen=True)
class Piece:
    kind: PieceKind
    value: str


class Notes:
    def __init__(self) -> None:
        self.buf = ""

    def push(self, text: str) -> list[Piece]:
        self.buf += text
        pieces: list[Piece] = []
        while True:
            opened = self.buf.find("[")
            if opened < 0:
                if self.buf:
                    pieces.append(Piece(PieceKind.TEXT, self.buf))
                    self.buf = ""
                break
            if opened:
                pieces.append(Piece(PieceKind.TEXT, self.buf[:opened]))
                self.buf = self.buf[opened:]
            closed = self.buf.find("]")
            if closed < 0:
                break
            pieces.append(Piece(PieceKind.NOTE, self.buf[1:closed].strip()))
            self.buf = self.buf[closed + 1 :]
        return pieces


class SentenceSplitter:
    def __init__(self) -> None:
        self.buf = ""

    def push(self, text: str) -> list[str]:
        self.buf += text
        out: list[str] = []
        while True:
            cut = next(
                (
                    i + 1
                    for i, c in enumerate(self.buf[:-1])
                    if (c in ".!?…" and self.buf[i + 1].isspace()) or c == "\n"
                ),
                None,
            )
            if cut is None:
                break
            sentence = clean(self.buf[:cut])
            self.buf = self.buf[cut:]
            if sentence:
                out.append(sentence)
        return out

    def finish(self) -> str | None:
        rest = clean(self.buf)
        self.buf = ""
        return rest or None
