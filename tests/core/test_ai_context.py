from pathlib import Path

import pytest

from paper_pile.core.ai.context import (
    MIN_PART_TOKENS,
    RESERVED_TOKENS,
    TRUNCATED,
    build_context,
    estimate_tokens,
    extract_mentions,
)
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.create_note("cur.md", "# Current\nsee [[Out]] and [md](sub/other.md)\n")
    v.create_note("Out.md", "outgoing note text")
    v.create_note("Mentioned.md", "mentioned body")
    v.create_note("back.md", "I link to [[cur]]")
    v.create_folder("sub")
    v.create_note("sub/other.md", "other body")
    v.create_note("tab.md", "tab body")
    return v


def kinds(ctx) -> list[str]:  # type: ignore[no-untyped-def]
    return [p.kind for p in ctx.parts]


def test_estimate_tokens() -> None:
    assert (
        estimate_tokens("") == 0 and estimate_tokens("abcd") == 1 and estimate_tokens("abcde") == 2
    )


def test_extract_mentions() -> None:
    assert extract_mentions("see @[[My note]] and @plain, @plain again; @[[A#B]]") == [
        "My note",
        "plain",
        "A#B",
    ]
    assert extract_mentions("mail me at a@b.com or email@x") == []
    assert extract_mentions("(@Idea.)") == ["Idea"]
    assert extract_mentions("no mentions") == []


def test_parts_come_in_priority_order(vault: Vault) -> None:
    idx = Index(vault)
    idx.sync()
    ctx = build_context(
        vault,
        current_path="cur.md",
        current_text=vault.read_text("cur.md"),
        selection="chosen text",
        mentions=["Mentioned"],
        open_tabs=[("tab.md", "tab body"), ("cur.md", "dup")],
        include_tabs=True,
        index=idx,
    )
    assert kinds(ctx) == ["selection", "note", "mention", "tab", "linked", "linked", "linked"]
    linked = [p.path for p in ctx.of("linked")]
    assert linked == ["Out.md", "sub/other.md", "back.md"]  # outgoing first, then backlinks
    assert ctx.of("tab")[0].path == "tab.md"  # the current note is not repeated as a tab
    assert ctx.summary() == "Context: selection, note, 1 mentioned, 1 tabs, 3 linked"


def test_tabs_are_only_included_when_asked(vault: Vault) -> None:
    ctx = build_context(vault, current_path="cur.md", current_text="x", open_tabs=[("tab.md", "t")])
    assert not ctx.of("tab")


def test_a_note_is_never_included_twice(vault: Vault) -> None:
    ctx = build_context(
        vault,
        current_path="cur.md",
        current_text=vault.read_text("cur.md"),
        mentions=["Out", "out.md", "cur"],
        open_tabs=[("Out.md", "o")],
        include_tabs=True,
    )
    assert [p.path for p in ctx.parts if p.path == "Out.md"] == ["Out.md"]
    assert not any(p.kind == "mention" and p.path == "cur.md" for p in ctx.parts)


def test_missing_mentions_are_reported(vault: Vault) -> None:
    ctx = build_context(vault, current_path="cur.md", current_text="x", mentions=["Ghost"])
    assert ctx.missing == ["Ghost"] and not ctx.of("mention")


def test_long_parts_are_truncated_at_a_line_and_marked(vault: Vault) -> None:
    big = "\n".join(f"line {i} " + "word " * 10 for i in range(500))
    ctx = build_context(vault, current_path="cur.md", current_text=big, budget=1000)
    (note,) = ctx.of("note")
    assert note.truncated and note.text.endswith(TRUNCATED)
    assert note.tokens <= 1000 * 0.6 + 5  # a note may take 60% of the budget
    assert "line 499" not in note.text
    assert "(some cut)" in ctx.summary()


def test_the_total_stays_within_the_budget(vault: Vault) -> None:
    for i in range(10):
        vault.create_note(f"m{i}.md", "text " * 2000)
    ctx = build_context(
        vault,
        current_path="cur.md",
        current_text="n " * 4000,
        selection="s " * 3000,
        mentions=[f"m{i}" for i in range(10)],
        budget=2000,
    )
    assert ctx.used <= 2000 - RESERVED_TOKENS + 10
    assert ctx.parts[0].kind == "selection"  # the selection comes first and may be cut itself


def test_parts_that_no_longer_fit_are_left_out(vault: Vault) -> None:
    ctx = build_context(
        vault, current_path="cur.md", current_text="x " * 3000, selection="s " * 3000, budget=900
    )
    assert kinds(ctx) == ["selection"]  # the selection used what there was
    assert ctx.parts[0].truncated
    ctx = build_context(vault, current_path="cur.md", current_text="short", budget=RESERVED_TOKENS)
    assert ctx.parts == []
    assert MIN_PART_TOKENS > 0


def test_empty_inputs_give_an_empty_context(vault: Vault) -> None:
    ctx = build_context(vault, current_path=None)
    assert ctx.parts == [] and ctx.summary() == "No context" and ctx.used == 0
    assert "paper-pile" in ctx.system_prompt()


def test_system_prompt_lists_the_parts_in_order(vault: Vault) -> None:
    ctx = build_context(
        vault,
        current_path="cur.md",
        current_text="NOTE TEXT",
        selection="SEL",
        mentions=["Mentioned"],
    )
    prompt = ctx.system_prompt("Ada")
    assert "The user is called Ada" in prompt
    order = [
        prompt.index(x)
        for x in ("## Selected text", "## Current note: cur.md", "## Mentioned note: Mentioned.md")
    ]
    assert order == sorted(order)
    assert "SEL" in prompt and "NOTE TEXT" in prompt and "mentioned body" in prompt


def test_unreadable_linked_notes_are_skipped(vault: Vault) -> None:
    vault.resolve("Out.md").write_bytes(b"\xff\xfe not utf8")
    ctx = build_context(vault, current_path="cur.md", current_text=vault.read_text("cur.md"))
    assert [p.path for p in ctx.of("linked")] == ["sub/other.md"]


def test_source_view_keeps_graphics_as_code() -> None:
    from paper_pile.core.ai.context import source_view

    text = "- a\n![pic](x.png) and ![[Note]]\n```mermaid\ngraph TD\n```\n"
    text += "```python\nprint('![z](q.png)')\n```"
    out = source_view(text)
    assert "`![pic](x.png)`" in out and "`![[Note]]`" in out
    assert "```text\ngraph TD" in out and "```mermaid" not in out
    assert "print('![z](q.png)')" in out and "`![z](q.png)`" not in out
    assert out.startswith("- a")
