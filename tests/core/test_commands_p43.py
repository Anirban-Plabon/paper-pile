from datetime import datetime
from pathlib import Path

import pytest

from paper_pile.core import commands_builtin
from paper_pile.core.command_actions import resolve
from paper_pile.core.commands import REGISTRY, CommandContext, Insert, OpenPicker
from paper_pile.core.config import Config
from paper_pile.core.links import wikilink_forms, wikilink_to
from paper_pile.core.parser import render_html
from paper_pile.core.picker import search_notes
from paper_pile.core.templates import render_template
from paper_pile.core.vault import Vault


def run(command_id: str, text: str, query: str, **kw: object) -> tuple[str, int]:
    """Type ``query`` (e.g. ``/code``) at the end of ``text``, run the command, return the new
    text and caret."""
    start = len(text)
    full = text + query
    ctx = CommandContext("a.md", full, start, **kw)  # type: ignore[arg-type]
    action = REGISTRY.run(command_id, ctx)
    edit = resolve(action, full, start, len(full))
    assert edit is not None
    out = full
    for c in sorted(edit.changes, key=lambda c: c.start, reverse=True):
        out = out[: c.start] + c.insert + out[c.end :]
    return out, edit.cursor


def test_code_block() -> None:
    text, caret = run("code", "", "/code")
    assert text == "```\n\n```\n" and caret == 4
    assert "<pre>" in render_html(text)


def test_math_block_and_inline() -> None:
    text, caret = run("math", "", "/math")
    assert text == "$$\n\n$$\n" and caret == 3
    from paper_pile.core.parser import math_spans

    assert math_spans("$$\nx\n$$\n")[1] == ["x"]
    assert run("math-inline", "see ", "/m") == ("see $$", 5)  # caret between the dollars


def test_blocks_start_on_their_own_line() -> None:
    text, caret = run("code", "words ", "/code")
    assert text == "words \n```\n\n```\n" and text[caret - 1] == "\n"
    text, _ = run("table", "# Title\n", "/table")
    assert text.startswith("# Title\n| Column 1")  # already at a line start: no extra newline
    text, _ = run("table", "intro ", "/table")
    assert text.startswith("intro \n| Column 1")


@pytest.mark.parametrize(
    ("cid", "needle"),
    [("flowchart", "flowchart TD"), ("sequence", "sequenceDiagram"), ("gantt", "gantt")],
)
def test_mermaid_blocks(cid: str, needle: str) -> None:
    text, _ = run(cid, "", "/x")
    assert text.startswith("```mermaid\n" + needle) and text.endswith("```\n")
    assert 'class="language-mermaid"' in render_html(text)


def test_table_is_a_valid_tidy_3x3_table() -> None:
    from paper_pile.core.tables import format_table, parse_table

    text, caret = run("table", "", "/table")
    html = render_html(text)
    assert "<table>" in html and html.count("<th>") == 3 and html.count("<tr>") == 3
    assert caret == len(text)  # after the table; the editor focuses the first body cell
    parsed = parse_table(text)
    assert parsed is not None and format_table(parsed) + "\n" == text  # already tidy
    action = REGISTRY.run("table", CommandContext("a.md", "/table", 0))
    assert isinstance(action, Insert) and action.focus_cell == (1, 0)


def test_callout() -> None:
    text, caret = run("callout", "", "/callout")
    assert text == "> **Note:** " and caret == len(text)
    html = render_html(text)
    assert "<blockquote>" in html and "<strong>Note:</strong>" in html


def test_date_and_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(commands_builtin, "_now", lambda: datetime(2026, 3, 9, 7, 5))
    assert run("date", "on ", "/date")[0] == "on 2026-03-09"
    assert run("time", "at ", "/time")[0] == "at 07:05"


def test_image_command_opens_the_image_picker() -> None:
    assert REGISTRY.run("image", CommandContext("a.md", "/i", 0)) == OpenPicker("image", "image")


def test_link_and_embed_open_the_note_picker() -> None:
    ctx = CommandContext("a.md", "/l", 0)
    assert REGISTRY.run("link", ctx) == OpenPicker("note", "link")
    assert REGISTRY.run("embed", ctx) == OpenPicker("note", "embed")


def test_template_only_when_a_templates_folder_is_set(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    cfg = Config(global_path=tmp_path / "none.toml", vault=tmp_path)
    ctx = CommandContext("a.md", "/t", 0, vault=vault, config=cfg)
    assert "template" not in [c.id for c in REGISTRY.all(ctx)]  # nothing configured
    cfg.set("vault.templates_folder", "Templates", scope="vault")
    assert "template" not in [c.id for c in REGISTRY.all(ctx)]  # configured but missing
    vault.create_folder("Templates")
    assert "template" in [c.id for c in REGISTRY.all(ctx)]
    assert REGISTRY.run("template", ctx) == OpenPicker("template", "template")
    assert "template" in [c.id for c in REGISTRY.all()]  # without a context nothing is hidden


def test_every_phase1_group_is_present_in_order() -> None:
    names = [g.name for g in REGISTRY.search("")]
    assert names == ["Basic blocks", "Code & math", "Diagrams", "Media", "Links", "Insert"]
    ids = {c.id for c in REGISTRY.all()}
    assert {"callout", "code", "math", "math-inline", "flowchart", "sequence", "gantt"} <= ids
    assert {"image", "table", "link", "embed", "date", "time", "template"} <= ids


# ---- the picker, link names and templates -----------------------------------------------------

PATHS = ["Idea.md", "ideas/other.md", "work/Plan.md", "work/deep/idea notes.md", "z.txt"]


def test_search_notes_ranks_names_above_folders() -> None:
    assert search_notes("idea", PATHS)[:2] == ["Idea.md", "work/deep/idea notes.md"]
    assert "ideas/other.md" in search_notes("idea", PATHS)
    assert search_notes("plan", PATHS)[0] == "work/Plan.md"
    assert search_notes("zzzz", PATHS) == []
    assert search_notes("", PATHS) == sorted(PATHS, key=str.lower)
    assert len(search_notes("", PATHS, limit=2)) == 2
    assert search_notes("pln", PATHS)[0] == "work/Plan.md"  # letters in order


def test_wikilink_to_writes_the_shortest_working_name() -> None:
    paths = {"a.md", "x/Idea.md", "y/Idea.md", "y/solo.md"}
    assert wikilink_to("y/solo.md", "a.md", paths) == "solo"
    assert wikilink_to("x/Idea.md", "a.md", paths) == "x/Idea"  # "Idea" is ambiguous
    assert (
        wikilink_to("y/Idea.md", "y/solo.md", paths) == "y/Idea"
    )  # not just "Idea": that is shared
    assert wikilink_to("a.md", "y/solo.md", paths) == "a"
    assert wikilink_to("a.md", "a.md", {"a.md", "d/a.md"}) == "/a"  # only the exact path
    assert wikilink_forms("x/y/z.md") == ["z", "y/z", "x/y/z", "/x/y/z"]
    assert wikilink_forms("x/z.md", ext=True) == ["z.md", "x/z.md", "/x/z.md"]


def test_template_placeholders() -> None:
    now = datetime(2026, 1, 2, 3, 4)
    out = render_template("# {{title}}\n{{date}} {{time}} {{other}}", title="Note", now=now)
    assert out == "# Note\n2026-01-02 03:04 {{other}}"
    assert render_template("plain", title="x", now=now) == "plain"
    assert isinstance(Insert("x"), Insert)
