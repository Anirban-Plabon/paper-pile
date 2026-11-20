"""The formatting menu's items (core/formatting.py): every item is a toggle and keeps the words
selected."""

import pytest

from paper_pile.core.command_actions import TextEdit
from paper_pile.core.formatting import (
    COLORS,
    INLINE,
    apply,
    clean_comment,
    comments,
    set_comment,
)


def run(text: str, edit: TextEdit | None) -> tuple[str, str]:
    """The text after ``edit`` and what it leaves selected."""
    assert edit is not None
    out = text
    for c in sorted(edit.changes, key=lambda c: c.start, reverse=True):
        out = out[: c.start] + c.insert + out[c.end :]
    assert edit.anchor is not None
    return out, out[edit.anchor : edit.cursor]


def toggle(text: str, word: str, kind: str, arg: str | None = None) -> tuple[str, str]:
    start = text.index(word)
    return run(text, apply(text, start, start + len(word), kind, arg))


@pytest.mark.parametrize("kind", list(INLINE))
def test_inline_mark_on_and_off(kind: str) -> None:
    opening, closing = INLINE[kind]
    text = "say hello world now"
    on, selected = toggle(text, "hello world", kind)
    assert on == f"say {opening}hello world{closing} now"
    assert selected == "hello world"
    start = on.index("hello")
    off, selected = run(on, apply(on, start, start + len("hello world"), kind))
    assert off == text
    assert selected == "hello world"


@pytest.mark.parametrize("kind", list(INLINE))
def test_selection_with_its_own_delimiters_unmarks(kind: str) -> None:
    opening, closing = INLINE[kind]
    text = f"a {opening}word{closing} b"
    out, selected = toggle(text, f"{opening}word{closing}", kind)
    assert out == "a word b"
    assert selected == "word"


def test_spaces_around_the_selection_stay_outside() -> None:
    assert toggle("a  word  b", "  word  ", "highlight")[0] == "a  ==word==  b"


def test_bold_and_italic_tell_their_stars_apart() -> None:
    assert toggle("x **w** y", "w", "italic")[0] == "x ***w*** y"
    assert toggle("x ***w*** y", "w", "italic")[0] == "x **w** y"
    assert toggle("x ***w*** y", "w", "bold")[0] == "x *w* y"
    assert toggle("x *w* y", "w", "bold")[0] == "x ***w*** y"


def test_lines_are_marked_one_by_one_inside_their_prefix() -> None:
    text = "intro\n- one\n> quoted\n\n## Head"
    out, selected = run(text, apply(text, 0, len(text), "highlight"))
    assert out == "==intro==\n- ==one==\n> ==quoted==\n\n## ==Head=="
    assert selected.startswith("intro==") and selected.endswith("==Head")


def test_mixed_selection_marks_what_is_not_marked_yet() -> None:
    text = "a\n- ==one==\n- two"
    out, _ = run(text, apply(text, 0, len(text), "highlight"))
    assert out == "==a==\n- ==one==\n- ==two=="
    again, _ = run(out, apply(out, 0, len(out), "highlight"))
    assert again == "a\n- one\n- two"


def test_empty_selection_does_nothing() -> None:
    assert apply("a  b", 1, 3, "bold") is None


def test_color_on_change_off() -> None:
    red, sel = toggle("x red y", "red", "color", "red")
    assert red == f'x <span style="color:{COLORS["red"]}">red</span> y' and sel == "red"
    start = red.index("red<")
    blue, sel = run(red, apply(red, start, start + 3, "color", "blue"))
    assert blue == f'x <span style="color:{COLORS["blue"]}">red</span> y' and sel == "red"
    start = blue.index("red<")
    plain, _ = run(blue, apply(blue, start, start + 3, "color", "blue"))  # same colour: off
    assert plain == "x red y"
    plain2, _ = run(blue, apply(blue, start, start + 3, "color", None))
    assert plain2 == "x red y"


def test_color_takes_a_code_and_refuses_junk() -> None:
    assert toggle("a b", "b", "color", "#ABC")[0] == 'a <span style="color:#abc">b</span>'
    assert apply("a b", 2, 3, "color", "url(x)") is None


def test_link_to_url_and_back() -> None:
    out, sel = toggle("see docs now", "docs", "link", "https://a.b/c d")
    assert out == "see [docs](https://a.b/c%20d) now" and sel == "docs"
    start = out.index("docs")
    back, sel = run(out, apply(out, start, start + 4, "link"))
    assert back == "see docs now" and sel == "docs"


def test_link_to_a_note() -> None:
    assert toggle("see docs", "docs", "link", "[[Docs]]")[0] == "see [[Docs|docs]]"
    assert toggle("see Docs", "Docs", "link", "[[Docs]]")[0] == "see [[Docs]]"
    out = "see [[Docs|docs]] x"
    start = out.index("docs")
    assert run(out, apply(out, start, start + 4, "link"))[0] == "see docs x"


def test_link_never_spans_lines() -> None:
    assert apply("a\nb", 0, 3, "link", "https://x") is None


def test_comment_goes_after_the_words() -> None:
    out, sel = toggle("plan due Friday.", "Friday", "comment", "check\nwith Sam")
    assert out == "plan due Friday%%check with Sam%%." and sel == "Friday"
    assert apply("a b", 2, 3, "comment", "   ") is None


def test_comment_text_cannot_end_the_comment_early() -> None:
    assert clean_comment("50%% off %") == "50% off"


def test_comments_are_found_and_edited() -> None:
    text = "a%%one%% b %%two%%"
    found = comments(text)
    marks = [(c.body, text[c.start : c.end]) for c in found]
    assert marks == [("one", "%%one%%"), ("two", "%%two%%")]
    edit = set_comment(text, found[1].start, "2")
    assert edit is not None
    out = text[: edit.changes[0].start] + edit.changes[0].insert + text[edit.changes[0].end :]
    assert out == "a%%one%% b %%2%%"
    gone = set_comment(text, found[0].start, "")
    assert gone is not None and gone.changes[0].insert == ""


@pytest.mark.parametrize(
    ("kind", "want"),
    [
        ("bullet", "- a\n- b"),
        ("numbered", "1. a\n2. b"),
        ("todo", "- [ ] a\n- [ ] b"),
        ("quote", "> a\n> b"),
        ("h1", "# a\n# b"),
        ("h2", "## a\n## b"),
    ],
)
def test_line_items_on_and_off(kind: str, want: str) -> None:
    text = "a\nb"
    out, _ = run(text, apply(text, 0, 3, kind))
    assert out == want
    back, _ = run(out, apply(out, 0, len(out), kind))
    assert back == text


def test_line_kind_replaces_another_marker_and_keeps_the_quote() -> None:
    text = "> - a\n> - b"
    assert run(text, apply(text, 0, len(text), "numbered"))[0] == "> 1. a\n> 2. b"


def test_quote_does_not_nest_quoted_lines() -> None:
    text = "- a\n> b"
    assert run(text, apply(text, 0, len(text), "quote"))[0] == "> - a\n> b"


def test_line_items_skip_empty_lines_and_the_line_after_a_full_line() -> None:
    text = "a\n\nb\nc"
    end = text.index("c")  # the selection ends at the start of "c": c is not taken
    assert run(text, apply(text, 0, end, "bullet"))[0] == "- a\n\n- b\nc"


def test_unknown_kind() -> None:
    with pytest.raises(ValueError):
        apply("a", 0, 1, "sparkle")


# ---- export ---------------------------------------------------------------------------------


def test_export_drops_comments_and_keeps_code() -> None:
    from paper_pile.core.formatting import strip_for_export

    text = (
        "---\ntitle: a // b\n---\n"
        "plan%%secret%% done // aside\n"
        "// whole line\n"
        "next ==hl== `a // b` and `==c==`\n"
        "see https://x.org/a and `x`//glued\n\n"
        "```\ncode // keep %%keep%%\n```\n"
    )
    out = strip_for_export(text)
    assert out == (
        "---\ntitle: a // b\n---\n"
        "plan done\n"
        "next ==hl== `a // b` and `==c==`\n"
        "see https://x.org/a and `x`//glued\n\n"
        "```\ncode // keep %%keep%%\n```\n"
    )
    plain = strip_for_export(text, keep_highlights=False)
    assert "next hl `a // b` and `==c==`" in plain


def test_export_keeps_a_note_without_comments_unchanged() -> None:
    from paper_pile.core.formatting import strip_for_export

    text = "# T\n\n- a\n- b  \n\n| x | y |\n| - | - |\n| 1 | 2 |\n"
    assert strip_for_export(text) == text
