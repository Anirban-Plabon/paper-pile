from paper_pile.core.parser import plain_line
from paper_pile.core.snippets import link_snippet


def test_plain_line_removes_markup() -> None:
    assert (
        plain_line("Target **body** text with [[Home]] link.").text
        == "Target body text with Home link."
    )
    assert plain_line("a `code` and *em* and ~~gone~~").text == "a code and em and gone"
    assert plain_line("see [the docs](https://e.org/x) now").text == "see the docs now"
    assert plain_line("![alt text|40](.a.assets/x.png) pic").text == "alt text pic"
    assert (
        plain_line("[[note|alias]] and [[folder/note#Head]]").text == "alias and folder/note > Head"
    )
    assert plain_line("math $x^2$ here").text == "math x^2 here"
    assert plain_line("line one\\\nline two").text == "line one line two"
    assert plain_line("`[[not a link]]` stays").text == "[[not a link]] stays"


def test_plain_line_finds_the_wanted_link() -> None:
    p = plain_line("Target **body** with [[Home|my home]] link.", "wiki", "Home|my home")
    assert p.hit is not None and p.text[p.hit[0] : p.hit[1]] == "my home"
    p = plain_line("a [one](a.md) and [two](b.md)", "md", "b.md")
    assert p.hit is not None and p.text[p.hit[0] : p.hit[1]] == "two"
    assert plain_line("no links", "wiki", "x").hit is None


def test_snippet_marks_the_link() -> None:
    text = "# Title\n- [ ] Target **body** text with [[Home]] link.\n"
    s = link_snippet(text, 2, "wiki", "Home")
    assert (s.before, s.hit, s.after) == ("Target body text with ", "Home", " link.")
    assert s.text == "Target body text with Home link."


def test_snippet_strips_block_markers() -> None:
    assert link_snippet("> - [[a]] x", 1, "wiki", "a").text == "a x"
    assert link_snippet("## Heading [[a]]", 1, "wiki", "a").text == "Heading a"
    assert link_snippet("1. [[a]] item", 1, "wiki", "a").text == "a item"


def test_snippet_is_cut_around_the_link() -> None:
    text = "start " + "word " * 80 + "[[Home]] " + "tail " * 80
    s = link_snippet(text, 1, "wiki", "Home", width=60)
    assert (
        len(s.text) <= 62 and s.hit == "Home" and s.before.startswith("…") and s.after.endswith("…")
    )
    short = link_snippet("x " * 100 + "[[Home]]", 1, "wiki", "Home", width=40)
    assert short.hit == "Home" and len(short.text) <= 42


def test_snippet_without_a_found_link_or_line() -> None:
    assert link_snippet("hello **x**", 1).text == "hello x" and link_snippet("hello", 1).hit == ""
    assert link_snippet("hello", 9, "wiki", "a").text == ""
    s = link_snippet("a  [[x]]   b", 1, "wiki", "x")
    assert s.text == "a x b" and s.hit == "x"
