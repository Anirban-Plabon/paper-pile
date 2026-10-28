"""Suggested prompts (PLAN §4.26): chosen by what is attached, plus the user's own file."""

from pathlib import Path

from paper_pile.core.ai.prompts import (
    MAX_SHOWN,
    load_prompts,
    prompts_file,
    selection_kind,
    suggestions,
)


def test_selection_kinds() -> None:
    assert selection_kind("Code block", "```py\nx\n```") == "code"
    assert selection_kind("Math block", "$$x$$") == "math"
    assert selection_kind("Diagram", "graph") == "diagram"
    assert selection_kind("Selected text", "| a | b |\n|---|---|\n| 1 | 2 |") == "table"
    assert selection_kind("Selected text", "```js\nlet a\n```") == "code"
    assert selection_kind("Selected text", "Plain words here.") == "prose"


def test_suggestions_fit_what_is_attached() -> None:
    assert suggestions([]) == []
    assert suggestions(["code"])[0] == "Explain this code"
    mixed = suggestions(["table", "note"])
    assert mixed[0] == "Summarize this table" and "Summarize this note" in mixed
    assert len(mixed) <= MAX_SHOWN


def test_own_prompts_follow_and_always_fit() -> None:
    own = ["Translate to Bengali", "Turn into a checklist"]
    shown = suggestions(["prose"], own)
    assert shown[-2:] == own and len(shown) <= MAX_SHOWN
    many = suggestions(["note"], [f"mine {i}" for i in range(10)])
    assert many[:2] == ["Summarize this note", "Outline this note"] and len(many) == MAX_SHOWN


def test_prompts_file(tmp_path: Path) -> None:
    f = tmp_path / "prompts.md"
    lines = ["# My prompts", "", "- Translate to Bengali", "* Turn into a checklist", "- "]
    f.write_text("\n".join([*lines, "- Translate to Bengali", "text", ""]))
    assert load_prompts(f) == ["Translate to Bengali", "Turn into a checklist"]
    assert load_prompts(tmp_path / "missing.md") == [] and load_prompts(None) == []
    assert prompts_file(tmp_path, "AI/prompts.md") == tmp_path / "AI/prompts.md"
    assert prompts_file(tmp_path, "") is None
