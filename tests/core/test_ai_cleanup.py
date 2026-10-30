"""P26.6: clean answers, finished and streamed (PLAN §4.29)."""

import pytest

from paper_pile.core.ai.cleanup import StreamCleaner, clean_reply, demote, heading_floor


@pytest.mark.parametrize(
    ("reply", "original", "clean"),
    [
        ("Translation:\nBonjour le monde.", "", "Bonjour le monde."),
        ("[B8]:\nNew text.", "", "New text."),
        ("<<<\nNew text.\n>>>", "", "New text."),
        ("New text.\n\n(Note: I kept the links.)", "", "New text."),
        ("---\ntitle: x\n---\nBody.", "Body old.", "Body."),
        ("---\ntitle: y\n---\nBody.", "---\ntitle: x\n---\nOld.", "---\ntitle: y\n---\nBody."),
        ("<think>long", "", ""),
        ("Line one.   \nLine two.  ", "", "Line one.\nLine two."),
    ],
)
def test_clean_reply_more_rules(reply: str, original: str, clean: str) -> None:
    assert clean_reply(reply, original) == clean


def stream(pieces: list[str], **kw: object) -> str:
    cleaner = StreamCleaner(**kw)  # type: ignore[arg-type]
    out = "".join(cleaner.feed(p) for p in pieces)
    return out + cleaner.finish()


def chars(text: str) -> list[str]:
    return list(text)  # the hardest case: one character at a time


def test_stream_drops_preamble_closing_and_fence() -> None:
    answer = "Sure! Here is the summary:\n```markdown\n- one\n- two\n\nMore.\n```\n\nLet me know!"
    assert stream(chars(answer)) == "- one\n- two\n\nMore."
    assert stream(["Plain answer.\n\nSecond paragraph."]) == "Plain answer.\n\nSecond paragraph."


def test_stream_drops_reasoning() -> None:
    assert stream(chars("<think>hmm, ok</think>\nThe answer.")) == "The answer."
    assert stream(["<thi", "nk>never ends"]) == ""


def test_stream_holds_back_only_the_last_paragraph() -> None:
    cleaner = StreamCleaner()
    assert cleaner.feed("First paragraph.\n\nSecond") == "First paragraph."
    assert cleaner.feed(" one.") == ""
    assert cleaner.finish() == "\n\nSecond one."  # the gap comes with what follows it


def test_stream_keeps_headings_below_the_section() -> None:
    answer = "# Summary\n\n## Points\n\n- a\n\n```\n# not a heading\n```"
    assert stream(chars(answer), heading_floor=2) == (
        "### Summary\n\n### Points\n\n- a\n\n```\n# not a heading\n```"
    )
    assert stream(["# My Note\n\nText."], title="My note") == "Text."
    assert demote("## A", 1) == "## A" and demote("# A", 2) == "### A" and demote("x", 3) == "x"


def test_heading_floor() -> None:
    note = "intro\n\n# A\n\ntext\n\n## B\n\n```\n# not a heading\n```\n\nend"
    assert heading_floor(note, 0) == 0
    assert heading_floor(note, note.index("text")) == 1
    assert heading_floor(note, len(note)) == 2


def test_new_text_gets_a_blank_line_after_its_headings() -> None:
    assert clean_reply("## Backups\nBack up nightly.") == "## Backups\n\nBack up nightly."
    code = "```md\n## not a heading\ntext\n```"
    assert clean_reply(code + "\n\nafter", "") == code + "\n\nafter"
    own = "## Mine\ntext"  # a rewrite of the user's own text keeps its layout
    assert clean_reply("## Mine\nnew text", own) == "## Mine\nnew text"
