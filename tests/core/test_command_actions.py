from pathlib import Path

import pytest

from paper_pile.core import commands_builtin  # noqa: F401  (registers the commands)
from paper_pile.core.command_actions import TextChange, TextEdit, remove_range, resolve
from paper_pile.core.commands import (
    REGISTRY,
    CommandContext,
    Insert,
    OpenNote,
    OpenPicker,
    ReplaceLinePrefix,
    ReplaceSelection,
)
from paper_pile.core.config import Config
from paper_pile.core.textpos import codepoint_index, utf16_index


def apply(text: str, edit: TextEdit) -> tuple[str, int]:
    """Apply ``edit`` the way the editor does; return (new text, caret)."""
    out = text
    for c in sorted(edit.changes, key=lambda c: c.start, reverse=True):
        out = out[: c.start] + c.insert + out[c.end :]
    return out, edit.cursor


def line_edit(text: str, prefix: str) -> tuple[str, int]:
    """Run ``ReplaceLinePrefix`` for a ``/q`` typed where the text contains the marker ``|``
    (the caret is right after the typed ``/q``)."""
    start = text.index("/")
    end = text.index("|")
    plain = text.replace("|", "")
    edit = resolve(ReplaceLinePrefix(prefix), plain, start, end)
    assert edit is not None
    return apply(plain, edit)


# ---- Insert / ReplaceSelection / non-edits -------------------------------------------------


def test_insert_replaces_the_typed_query() -> None:
    edit = resolve(Insert("DONE"), "a /do b", 2, 5)
    assert edit and apply("a /do b", edit) == ("a DONE b", 6)


def test_insert_with_cursor_offset() -> None:
    edit = resolve(Insert("[]()", cursor_offset=1), "/l", 0, 2)
    assert edit and apply("/l", edit) == ("[]()", 1)


def test_replace_selection() -> None:
    edit = resolve(ReplaceSelection("X"), "ab /c", 3, 5)
    assert edit and apply("ab /c", edit) == ("ab X", 4)


def test_actions_that_are_not_edits() -> None:
    assert resolve(OpenNote("a.md"), "/x", 0, 2) is None
    assert resolve(OpenPicker("note"), "/x", 0, 2) is None
    assert remove_range(3, 6) == TextEdit((TextChange(3, 6, ""),), 3)


# ---- ReplaceLinePrefix ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "prefix", "after", "caret"),
    [
        ("/h2|", "## ", "## ", 3),  # empty line
        ("/h2|\n", "## ", "## \n", 3),
        ("word /h2|", "# ", "# word ", 7),  # typed after text: text stays, marker added
        ("/h2|rest", "## ", "## rest", 3),  # caret stays before the existing text
        ("  /h2|", "- ", "  - ", 4),  # indentation kept
        ("# old /h2|", "## ", "## old ", 7),  # heading replaced
        ("###### deep /h2|", "# ", "# deep ", 7),
        ("- item /q|", "> ", "> item ", 7),  # bullet -> quote
        ("- [ ] task /q|", "1. ", "1. task ", 8),  # task -> numbered
        ("- [x] done /q|", "- ", "- done ", 7),
        ("1. one /q|", "- [ ] ", "- [ ] one ", 10),
        ("12) one /q|", "- ", "- one ", 6),
        ("> quoted /q|", "", "quoted ", 7),  # back to plain text
        ("> - nested /q|", "# ", "# nested ", 9),  # every leading marker goes
        ("*emphasis* /h|", "# ", "# *emphasis* ", 13),  # not a marker: no space after `*`
        ("#hashtag /h|", "# ", "# #hashtag ", 11),  # `#` needs a space to be a heading
    ],
)
def test_replace_line_prefix(before: str, prefix: str, after: str, caret: int) -> None:
    assert line_edit(before, prefix) == (after, caret)


def test_same_marker_again_clears_it() -> None:
    assert line_edit("## title /h2|", "## ") == ("title ", 6)
    assert line_edit("- [ ] t /todo|", "- [ ] ") == ("t ", 2)
    assert line_edit("text /text|", "") == ("text ", 5)


def test_only_the_current_line_changes() -> None:
    text = "first\n# second /h\nthird"
    start = text.index("/")
    edit = resolve(ReplaceLinePrefix("- "), text, start, start + 2)
    assert edit and apply(text, edit) == ("first\n- second \nthird", len("first\n- second "))


def test_last_line_without_newline_and_crlf_free() -> None:
    assert line_edit("a\n/h1|", "# ") == ("a\n# ", 4)


# ---- UTF-16 offsets ------------------------------------------------------------------------


def test_textpos_round_trip_with_emoji() -> None:
    text = "a😀b𝄞c"
    assert [utf16_index(text, i) for i in range(len(text) + 1)] == [0, 1, 3, 4, 6, 7]
    assert [codepoint_index(text, u) for u in range(8)] == [0, 1, 1, 2, 3, 3, 4, 5]
    assert codepoint_index(text, 99) == len(text)
    assert all(codepoint_index(text, utf16_index(text, i)) == i for i in range(len(text) + 1))


# ---- the built-in commands -----------------------------------------------------------------


def ctx(text: str = "", cursor: int = 0) -> CommandContext:
    return CommandContext("a.md", text, cursor)


def test_builtin_commands_are_registered_and_well_formed() -> None:
    cmds = REGISTRY.all()
    ids = [c.id for c in cmds]
    assert len(ids) == len(set(ids))
    assert {
        "text",
        "h1",
        "h2",
        "h3",
        "h4",
        "bullet",
        "numbered",
        "todo",
        "quote",
        "divider",
    } <= set(ids)
    context = ctx("x\n/y", 4)
    for c in cmds:
        assert c.title and c.group and c.icon
        if c.available(context):  # e.g. templates need a templates folder
            assert REGISTRY.run(c.id, context) is not None


def test_builtin_groups_start_with_basic_blocks() -> None:
    groups = REGISTRY.search("")
    assert groups[0].name == "Basic blocks"


def test_search_finds_the_obvious_commands() -> None:
    first = lambda q: REGISTRY.search(q)[0].commands[0].id  # noqa: E731
    assert first("h2") == "h2"
    assert first("todo") == "todo"
    assert first("checkbox") == "todo"
    assert first("hr") == "divider"
    assert first("quote") == "quote"


def test_divider_gets_a_blank_line_under_text(tmp_path: Path) -> None:
    def run(text: str, at: int, config: Config | None = None) -> object:
        c = CommandContext("a.md", text, at, config=config, end=at + 1)
        return REGISTRY.run("divider", c)

    assert run("para\n/", 5) == Insert("\n---\n", 5)
    assert run("para\n\n/", 6) == Insert("---\n", 4)
    assert run("/", 0) == Insert("---\n", 4)
    # wrapped like every block: an empty line below it too when text follows
    assert run("# Head\n/\nnext", 7) == Insert("\n---\n", 5)
    assert run("a\n/\n\nb", 2) == Insert("\n---", 4)  # the empty line below is already there
    off = Config(global_path=tmp_path / "none.toml", vault=tmp_path)
    off.set("editor.block_spacing", False, scope="vault")
    assert run("para\n/", 5, off) == Insert("\n---\n")


def test_divider_end_to_end_never_makes_a_setext_heading() -> None:
    from paper_pile.core.parser import render_html

    text = "para\n/div"
    action = REGISTRY.run("divider", ctx(text, 5))
    edit = resolve(action, text, 5, 9)
    assert edit
    new, _ = apply(text, edit)
    assert "<h2>" not in render_html(new) and "<hr" in render_html(new)


@pytest.mark.parametrize(
    ("text", "start"),
    [
        ("para\n/page", 5),  # under text
        ("para /page", 5),  # after text on the same line
        ("/page", 0),  # empty note
        ("# Head\n/page\nnext", 7),  # text right below
        ("a\n\n/page\n\nb", 3),  # empty lines already there
        ("- item /page", 7),  # in a list item: the break goes below the list
    ],
)
def test_page_break_is_a_break_even_after_typing(tmp_path: Path, text: str, start: int) -> None:
    from paper_pile.core.parser import page_breaks

    off = Config(global_path=tmp_path / "none.toml", vault=tmp_path)
    off.set("editor.block_spacing", False, scope="vault")  # the empty lines do not depend on it
    end = start + len("/page")
    action = REGISTRY.run("page-break", CommandContext("a.md", text, start, config=off, end=end))
    edit = resolve(action, text, start, end)
    assert edit
    new, caret = apply(text, edit)
    typed = new[:caret] + "typed" + new[caret:]
    assert [b.effective for b in page_breaks("before\n\n" + typed)] == [True]


def test_page_break_found_by_its_names() -> None:
    first = lambda q: REGISTRY.search(q)[0].commands[0].id  # noqa: E731
    assert first("page break") == "page-break"
    assert first("pagebreak") == "page-break"


def test_page_break_is_written_as_dash_dash_dash_slash() -> None:
    text = "a\n/page\nb"
    action = REGISTRY.run("page-break", CommandContext("a.md", text, 2, end=7))
    edit = resolve(action, text, 2, 7)
    assert edit
    new, caret = apply(text, edit)
    assert new == "a\n\n---/\n\n\nb" and new[caret:] == "\nb"


@pytest.mark.parametrize(
    "old,new", [("abc", "abc"), ("abc", "aXc"), ("", "new"), ("old", ""), ("a\nb\nc", "a\nc")]
)
def test_whole_text_edit_changes_only_the_part_that_differs(old: str, new: str) -> None:
    from paper_pile.core.command_actions import whole_text_edit

    edit = whole_text_edit(old, new)
    (change,) = edit.changes
    assert old[: change.start] + change.insert + old[change.end :] == new
    assert len(change.insert) == len(new) - (len(old) - (change.end - change.start))
