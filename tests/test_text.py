import pytest

from m8py.text import Notes, Piece, PieceKind, SentenceSplitter, clean, delivery_note


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"Hello there."', "Hello there."),
        ("“Hello.”", "Hello."),
        ("*bold* _word_ #tag ~x~ `code`", "bold word tag x code"),
        ("Hi 😀 soldier ⚡!", "Hi soldier !"),
        ("[looks around] Go.", "Go."),
        ("Go (nods) now.", "Go now."),
        ("Go (unclosed forever", "Go"),
        ("(laughs) Fine.", "(laugh) Fine."),
        ("(LAUGHTER) Fine.", "(laugh) Fine."),
        ("(sighing) (coughs) (clears his throat) Yes.", "(sigh) (cough) (clears throat) Yes."),
        ("(whispers) ...", ""),
        ("*** 😀", ""),
    ],
)
def test_clean(raw, expected):
    assert clean(raw) == expected


def test_notes_stream_boundaries():
    n = Notes()
    assert n.push("Hello [ang") == [Piece(PieceKind.TEXT, "Hello ")]
    assert n.push("ry]world") == [Piece(PieceKind.NOTE, "angry"), Piece(PieceKind.TEXT, "world")]


def test_notes_mid_sentence_and_unclosed():
    n = Notes()
    assert n.push("one[ low ]two[") == [
        Piece(PieceKind.TEXT, "one"),
        Piece(PieceKind.NOTE, "low"),
        Piece(PieceKind.TEXT, "two"),
    ]
    assert n.push("held") == []


def test_sentence_stream_boundaries():
    s = SentenceSplitter()
    assert s.push("One. Two!") == ["One."]
    assert s.push(" Three?\nFour") == ["Two!", "Three?"]
    assert s.finish() == "Four"


def test_sentence_requires_following_whitespace():
    s = SentenceSplitter()
    assert s.push("version 1.2 is here.\nNext") == ["version 1.2 is here."]
    assert s.finish() == "Next"


def test_note_causes_mid_sentence_flush():
    notes = Notes()
    split = SentenceSplitter()
    out = []
    how = ""
    for chunk in ("Hello brave [quiet", "]soldier. Next"):
        for p in notes.push(chunk):
            if p.kind is PieceKind.TEXT:
                out += [(x, how) for x in split.push(p.value)]
            else:
                if rest := split.finish():
                    out.append((rest, how))
                how = p.value
    if rest := split.finish():
        out.append((rest, how))
    assert out == [("Hello brave", ""), ("soldier.", "quiet"), ("Next", "quiet")]


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        ("quiet and tired", "quiet and tired"),
        ("yelling over the gunfire", "yelling over the gunfire"),
        ("reloads his rifle", ""),
        ("walks toward the Warthog", ""),
    ],
)
def test_delivery_note_allowlist(note, expected):
    assert delivery_note(note) == expected
