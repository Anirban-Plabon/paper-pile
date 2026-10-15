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


def test_divider_gets_a_blank_line_under_text() -> None:
    assert REGISTRY.run("divider", ctx("para\n/", 5)) == Insert("\n---\n")
    assert REGISTRY.run("divider", ctx("para\n\n/", 6)) == Insert("---\n")
    assert REGISTRY.run("divider", ctx("/", 0)) == Insert("---\n")


def test_divider_end_to_end_never_makes_a_setext_heading() -> None:
    from paper_pile.core.parser import render_html

    text = "para\n/div"
    action = REGISTRY.run("divider", ctx(text, 5))
    edit = resolve(action, text, 5, 9)
    assert edit
    new, _ = apply(text, edit)
    assert "<h2>" not in render_html(new) and "<hr" in render_html(new)
