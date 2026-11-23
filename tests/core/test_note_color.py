import pytest

from paper_pile.core.note_color import NOTE_COLORS, note_color, with_color


def test_reads_the_colour() -> None:
    assert note_color("---\ntitle: a\ncolor: red\n---\n\ntext\n") == "red"
    assert note_color("---\ncolor: 'Blue'\n---\n") == "blue"
    assert note_color("---\ncolor: chartreuse\n---\n") == ""
    assert note_color("color: red\n") == ""  # not front matter
    assert note_color("---\ntitle: a\n---\ncolor: red\n") == ""  # in the body
    assert note_color("") == ""
    assert note_color("---\ncolor: red\nno closing line\n") == ""
    assert note_color("---\r\ncolor: green\r\n---\r\n") == "green"
    assert len(NOTE_COLORS) == 8


def test_sets_in_existing_front_matter() -> None:
    text = "---\ntitle: a\n---\n\nbody\n"
    out = with_color(text, "green")
    assert out == "---\ntitle: a\ncolor: green\n---\n\nbody\n"
    assert with_color(out, "pink") == "---\ntitle: a\ncolor: pink\n---\n\nbody\n"
    assert with_color(out, "") == text


def test_creates_and_removes_front_matter() -> None:
    out = with_color("body\n", "red")
    assert out == "---\ncolor: red\n---\n\nbody\n"
    assert note_color(out) == "red"
    assert with_color(out, "") == "body\n"
    assert with_color("", "red") == "---\ncolor: red\n---\n"
    assert with_color("body\n", "") == "body\n"


def test_keeps_crlf() -> None:
    out = with_color("---\r\ntitle: a\r\n---\r\nx\r\n", "red")
    assert out == "---\r\ntitle: a\r\ncolor: red\r\n---\r\nx\r\n"


def test_front_matter_only_without_final_newline() -> None:
    assert with_color("---\ntitle: a\n---", "red") == "---\ntitle: a\ncolor: red\n---"


def test_unknown_colour_raises() -> None:
    with pytest.raises(ValueError):
        with_color("x", "chartreuse")


def test_editor_knows_the_same_colours() -> None:
    import re
    from pathlib import Path

    js = Path(__file__).parents[2] / "tools" / "editor_src" / "blocks.js"
    m = re.search(r"const NOTE_COLORS = \[([^\]]*)\]", js.read_text())
    assert m is not None
    assert tuple(re.findall(r'"(\w+)"', m.group(1))) == NOTE_COLORS
