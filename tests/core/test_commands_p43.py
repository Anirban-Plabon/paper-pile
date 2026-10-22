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
    ctx = CommandContext("a.md", full, start, end=len(full), **kw)  # type: ignore[arg-type]
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
    assert text == "words \n\n```\n\n```\n" and text[caret - 1] == "\n"
    text, _ = run("table", "# Title\n", "/table")
    assert text.startswith("# Title\n\n| Column 1")  # an empty line between them
    text, _ = run("table", "intro ", "/table")
    assert text.startswith("intro \n\n| Column 1")


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
    assert text == "> **Note:** \n" and caret == len(text) - 1  # an empty line below to escape to
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
    assert names == ["Basic blocks", "Code & math", "Diagrams", "Media", "Links", "Insert", "AI"]
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


# ---- an empty line after lists, quotes and blocks ----------------------------------------------


def typed(text: str, query: str) -> tuple[str, int, int]:
    """``text`` with ``query`` typed where its ``|`` is: (full text, start, end)."""
    i = text.index("|")
    full = text[:i] + query + text[i + 1 :]
    return full, i, i + len(query)


def apply_command(command_id: str, template: str, query: str) -> str:
    full, start, end = typed(template, query)
    ctx = CommandContext("a.md", full, start, end=end)
    action = REGISTRY.run(command_id, ctx)
    edit = resolve(action, full, start, end)
    assert edit is not None
    out = full
    for c in sorted(edit.changes, key=lambda c: c.start, reverse=True):
        out = out[: c.start] + c.insert + out[c.end :]
    return out


@pytest.mark.parametrize("cid", ["bullet", "numbered", "todo", "quote"])
def test_list_and_quote_commands_leave_an_empty_line_after(cid: str) -> None:
    prefix = {"bullet": "- ", "numbered": "1. ", "todo": "- [ ] ", "quote": "> "}[cid]
    # end of the note: a line below
    assert apply_command(cid, "|", "/x") == prefix + "\n"
    # text right below: separated by an empty line, so it is not swallowed
    assert apply_command(cid, "|\nnext", "/x") == prefix + "\n\nnext"
    # already an empty line: nothing added
    assert apply_command(cid, "|\n\nnext", "/x") == prefix + "\n\nnext"
    # the next line is part of the same kind of block: do not split it
    assert apply_command(cid, "|\n- more", "/x") == prefix + "\n- more"
    assert apply_command(cid, "|\n> more", "/x") == prefix + "\n> more"
    assert apply_command(cid, "|\n   indented", "/x") == prefix + "\n   indented"


def test_blocks_leave_an_empty_line_after() -> None:
    assert apply_command("code", "|", "/c") == "```\n\n```\n"
    assert apply_command("code", "|\ntext", "/c") == "```\n\n```\n\ntext"
    assert apply_command("code", "|\n\ntext", "/c") == "```\n\n```\n\ntext"  # one is enough
    assert apply_command("math", "|\ntext", "/m") == "$$\n\n$$\n\ntext"
    assert apply_command("table", "|\ntext", "/t").endswith("|\n\ntext")
    assert apply_command("flowchart", "|\ntext", "/f").endswith("```\n\ntext")
    assert apply_command("callout", "|", "/c") == "> **Note:** \n"
    assert apply_command("callout", "|\ntext", "/c") == "> **Note:** \n\ntext"
    assert apply_command("callout", "|\n> more", "/c") == "> **Note:** \n> more"


def test_headings_get_empty_lines_around_them() -> None:
    assert apply_command("h1", "|\ntext", "/h") == "# \n\ntext"
    assert apply_command("h1", "above\n|\ntext", "/h") == "above\n\n# \n\ntext"
    assert apply_command("h2", "above\n\n|\n\ntext", "/h") == "above\n\n## \n\ntext"


def test_list_items_continue_a_list_above_without_a_gap() -> None:
    assert apply_command("todo", "- [ ] one\n|", "/t") == "- [ ] one\n- [ ] \n"
    assert apply_command("bullet", "words\n|", "/b") == "words\n\n- \n"


class _Settings:
    def __init__(self, **values: object) -> None:
        self.values = values

    def get(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)


def apply_without_spacing(command_id: str, template: str, query: str) -> str:
    full, start, end = typed(template, query)
    off = _Settings(**{"editor.block_spacing": False})
    ctx = CommandContext("a.md", full, start, end=end, config=off)  # type: ignore[arg-type]
    edit = resolve(REGISTRY.run(command_id, ctx), full, start, end)
    assert edit is not None
    out = full
    for c in sorted(edit.changes, key=lambda c: c.start, reverse=True):
        out = out[: c.start] + c.insert + out[c.end :]
    return out


def test_setting_off_keeps_blocks_on_their_own_lines_only() -> None:
    assert apply_without_spacing("h1", "above\n|\ntext", "/h") == "above\n# \ntext"
    assert apply_without_spacing("code", "words |", "/c") == "words \n```\n\n```\n"
    assert apply_without_spacing("code", "a\n|\nb", "/c") == "a\n```\n\n```\nb"
    # lists still end with an empty line, so the next text is not pulled into them
    assert apply_without_spacing("bullet", "|\nnext", "/b") == "- \n\nnext"


# ---- AI commands --------------------------------------------------------------------------------


def test_ai_commands_exist_and_need_a_selection_only_where_it_makes_sense() -> None:
    from paper_pile.core.commands import StreamInsert

    without = CommandContext("a.md", "text", 0)
    with_sel = CommandContext("a.md", "some text", 0, selection=(0, 4))
    ids_without = {c.id for c in REGISTRY.all(without)}
    ids_with = {c.id for c in REGISTRY.all(with_sel)}
    assert {"ai-summarize", "ai-continue", "ai-ask"} <= ids_without
    assert "ai-explain" not in ids_without and "ai-fix" not in ids_without
    assert {"ai-explain", "ai-fix"} <= ids_with
    fix = REGISTRY.run("ai-fix", with_sel)
    assert isinstance(fix, StreamInsert) and fix.replace_selection and fix.source == "selection"
    ask = REGISTRY.run("ai-ask", without)
    assert isinstance(ask, StreamInsert) and ask.ask
    cont = REGISTRY.run("ai-continue", without)
    assert isinstance(cont, StreamInsert) and cont.source == "before" and not cont.replace_selection
    assert resolve(cont, "x/c", 0, 1) is None  # not a text edit: the editor streams the answer


def test_ai_commands_are_found_by_their_names() -> None:
    first = lambda q: REGISTRY.search(q)[0].commands[0].id  # noqa: E731
    assert first("summar") == "ai-summarize" and first("tldr") == "ai-summarize"
    assert first("continue") == "ai-continue"
    assert [c.badge for c in REGISTRY.search("ask")[0].commands][:1] == ["AI"]
