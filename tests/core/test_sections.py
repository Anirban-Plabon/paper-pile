from paper_pile.core.sections import (
    current_section,
    next_start,
    note_title,
    previous_start,
    section_heads,
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


def test_sections_are_h1_and_h2_only() -> None:
    heads = section_heads(NOTE)
    assert [(h.text, h.line) for h in heads] == [("One", 6), ("Two", 9), ("Three", 12)]
    assert current_section(heads, 4) is None  # above the first section
    assert current_section(heads, 8).text == "One"  # type: ignore[union-attr]
    assert current_section(heads, 9).text == "Two"  # type: ignore[union-attr]


def test_previous_and_next() -> None:
    heads = section_heads(NOTE)
    assert next_start(heads, 1) == 6
    assert next_start(heads, 6) == 9  # at "One": the next one
    assert next_start(heads, 12) is None
    assert previous_start(heads, 11) == 9  # inside "Two": its start
    assert previous_start(heads, 9) == 6  # at "Two": the one before
    assert previous_start(heads, 8) == 6
    assert previous_start(heads, 6) is None
    assert previous_start(heads, 2) is None
