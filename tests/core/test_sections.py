from paper_pile.core.sections import (
    current_section,
    next_start,
    note_title,
    previous_start,
    section_heads,
    short_label,
    trail,
)

NOTE = """---
title: My plan
---
intro

# One
text
### deep
## Two
text

# Three
"""


def test_note_title_prefers_the_property() -> None:
    assert note_title(NOTE, "d/plan.md") == "My plan"
    assert note_title("# Hi\n", "d/plan.md") == "plan"
    assert note_title("---\ntitle:\n---\n", "plan.md") == "plan"  # empty: the name
    assert note_title("---\ntitle: [\n---\n", "plan.md") == "plan"  # broken front matter


def test_sections_are_h1_to_h3() -> None:
    heads = section_heads(NOTE)
    assert [(h.text, h.line) for h in heads] == [
        ("One", 6),
        ("deep", 8),
        ("Two", 9),
        ("Three", 12),
    ]
    assert current_section(heads, 4) is None  # above the first section
    assert current_section(heads, 7).text == "One"  # type: ignore[union-attr]
    assert current_section(heads, 9).text == "Two"  # type: ignore[union-attr]


def test_previous_and_next() -> None:
    heads = section_heads(NOTE)
    assert next_start(heads, 1) == 6
    assert next_start(heads, 6) == 8  # at "One": the next one (### deep)
    assert next_start(heads, 12) is None
    assert previous_start(heads, 11) == 9  # inside "Two": its start
    assert previous_start(heads, 9) == 8  # at "Two": the one before (### deep)
    assert previous_start(heads, 6) is None
    assert previous_start(heads, 2) is None


def test_trail_holds_the_headings_above_the_view() -> None:
    heads = section_heads(NOTE)
    names = lambda top: [h.text for h in trail(heads, top)]  # noqa: E731
    assert names(1) == []
    assert names(6) == []  # "# One" still on screen at the top: only the title
    assert names(7) == ["One"]
    assert names(9) == ["One", "deep"]
    assert names(10) == ["One", "Two"]  # ## Two closes ### deep
    assert names(13) == ["Three"]


def test_short_label() -> None:
    assert short_label("One two three") == "One two three"
    assert short_label("One two three four") == "One two three…"
    assert short_label("  a   b  ", 1) == "a…"
