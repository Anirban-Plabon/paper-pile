"""P26.12: where an answer command's text goes (AI_EDITS §6.1)."""

from paper_pile.core.ai.cleanup import StreamCleaner
from paper_pile.core.ai.placement import already_answered, answer_point

NOTE = """# Guide

Intro text here.

## Setup

- one
  - nested
- two

> quoted
> more

| a | b |
|---|---|
| 1 | 2 |

```py
x = 1
```

Last line.
"""


def at(text: str) -> tuple[int, int]:
    i = NOTE.index(text)
    return i, i + len(text)


def test_after_the_whole_block_never_inside_it() -> None:
    p = answer_point(NOTE, *at("Intro text"))
    assert NOTE[p.offset - len("here.") : p.offset] == "here." and p.lead == "\n\n"
    p = answer_point(NOTE, *at("one"))  # the first item: after the whole list
    assert NOTE[: p.offset].endswith("- two") and p.avoid_bullet == "-"
    p = answer_point(NOTE, *at("quoted"))
    assert NOTE[: p.offset].endswith("> more")
    p = answer_point(NOTE, *at("| 1"))
    assert NOTE[: p.offset].rstrip("\n").endswith("| 1 | 2 |")
    p = answer_point(NOTE, *at("x = 1"))
    assert NOTE[: p.offset].endswith("```") and p.heading_floor == 2


def test_whole_note_goes_at_the_end() -> None:
    p = answer_point(NOTE, 0, len(NOTE), whole=True)
    assert p.offset == len(NOTE.rstrip("\n")) and p.lead == "\n\n" and p.heading_floor == 2
    empty = answer_point("", 0, 0, whole=True)
    assert (empty.offset, empty.lead) == (0, "")


def test_heading_floor_at_the_point() -> None:
    assert answer_point(NOTE, *at("Intro text")).heading_floor == 1


def test_bullets_switch_next_to_a_list() -> None:
    cleaner = StreamCleaner(avoid_bullet="-")
    out = cleaner.feed("- a\n  - b\n- c\n\nnext\n\n") + cleaner.finish()
    assert out.startswith("* a\n  - b\n* c")


def test_already_has_a_summary() -> None:
    note = "# Plan\n\n## Summary\n\nShort.\n\n## Details\n\nLong text.\n"
    there = note.index("Short.")
    assert (
        already_answered(note, there, "ai-summarize") == "This note already has a Summary (line 3)."
    )
    assert already_answered(note, note.index("Long"), "ai-summarize") == ""  # another section
    assert already_answered(note, there, "ai-outline") == ""
    label = "Intro.\n\n**TL;DR:** in short.\n"
    assert "TL;DR (line 3)" in already_answered(label, 0, "ai-summarize")
