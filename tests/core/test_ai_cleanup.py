"""P26.6: clean answers, finished and streamed (PLAN §4.29)."""

import re

import pytest

from paper_pile.core.ai.cleanup import (
    StreamCleaner,
    clean_reply,
    demote,
    heading_floor,
    open_display_math,
    open_math_at,
    streaming_view,
)


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


def test_stream_writes_a_paragraph_as_it_comes() -> None:
    """User 2026-11-19: answers came into the note block by block; now character by character
    (only a paragraph's first characters wait, until they cannot be a closing remark)."""
    cleaner = StreamCleaner()
    para = "The backups run every night at two o'clock and keep a week of copies."
    seen = [cleaner.feed(c) for c in para]
    written = "".join(seen)
    assert written and len(written) > len(para) - 5  # streamed before the paragraph ended
    assert sum(1 for s in seen if s) > 20  # in many small pieces, not one block
    assert written + cleaner.finish() == para


def test_stream_holds_a_closing_remark_until_it_is_not_the_last() -> None:
    answer = "Text here that is long enough.\n\nLet me know if you want more.\n\nMore text, long."
    assert stream(chars(answer)) == answer
    assert stream(chars("Text here that is long enough.\n\nLet me know if you want more.")) == (
        "Text here that is long enough."
    )


@pytest.mark.parametrize(
    "answer",
    [
        "A line with trailing spaces   \nnext line of the paragraph here.",
        "Para one is long enough here.\n\n\n\nPara two is long enough too.",
        "Some code here, look:\n\n```python\nx = 1\n\ny = 2\n```\n\nafter the code, long text.",
        "- item one of the list here\n- item two\n  - nested item\n\n## Head\n\nBody text follows.",
    ],
)
def test_stream_char_by_char_matches_a_whole_answer(answer: str) -> None:
    assert stream(chars(answer)) == stream([answer])
    assert stream([answer]) == re.sub(r"\n{3,}", "\n\n", clean_reply(answer, "x"))


def test_open_math_is_found() -> None:
    assert open_math_at("the area is $\\frac{a}{") == 12
    assert open_math_at("the area is $a^2$ and") is None
    assert open_math_at("costs \\$5 and `$x` and $$") is None
    assert open_display_math("text\n$$\n\\int_0^1") == 5
    assert open_display_math("$$x$$ done") is None


def test_streaming_view_leaves_out_an_unfinished_formula() -> None:
    assert streaming_view("Area $\\pi r") == "Area "
    assert streaming_view("Area $\\pi r^2$.") == "Area $\\pi r^2$."
    assert streaming_view("Intro\n\n$$\n\\sum_i") == "Intro\n\n"
    assert streaming_view("one $x\nnext line") == "one $x\nnext line"  # a line ended: no formula


def test_stream_writes_an_inline_formula_in_one_piece() -> None:
    """User 2026-11-19: inline math jumped as it was written (raw TeX first, then the formula)."""
    cleaner = StreamCleaner()
    pieces = [cleaner.feed(c) for c in "The circle's area is $\\pi r^2$ for radius r, as known."]
    formula = [p for p in pieces if "$" in p]
    assert formula == ["$\\pi r^2$"] or all(p.count("$") % 2 == 0 for p in formula)
    assert (
        "".join(pieces) + cleaner.finish()
        == "The circle's area is $\\pi r^2$ for radius r, as known."
    )


def test_stream_writes_a_display_formula_once_it_is_closed() -> None:
    cleaner = StreamCleaner()
    out = [
        cleaner.feed(c)
        for c in "Long enough text first here.\n\n$$\n\\int_0^1 x\\,dx\n$$\n\nAfter."
    ]
    joined = "".join(out)
    assert "\\int" in joined and joined.count("$$") == 2  # written once closed, before the end
    assert not any(p.count("$$") == 1 for p in out)
