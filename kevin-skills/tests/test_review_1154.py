"""Ticket 20261029-115403-review: the Orders line held clashing entries ("stay back and watch
the flank" beside "move perpetually ahead of Chief"), rule text ("keep the player's conditions
and wording") and things the player said to someone else ("periodically look at the contents
of my transcript"). The actor must not act on those."""

from pathlib import Path


def test_prompt_says_the_orders_line_can_be_wrong():
    prompt = (Path(__file__).parents[1] / "actor" / "prompt.md").read_text()
    assert "The Orders line is a rough list" in prompt
    assert '"look at my transcript"' in prompt and "Never pick nofit for them" in prompt
