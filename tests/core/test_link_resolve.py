import pytest

from paper_pile.core.links import (
    link_keys,
    new_note_path,
    norm_name,
    resolve_md_link,
    resolve_wikilink,
)
from paper_pile.core.parser import find_heading, headings

PATHS = ["a.md", "Notes/Idea.md", "Notes/deep/Idea.md", "work/plan.txt", "work/Plan.md", "x/b.md"]


def test_norm_name() -> None:
    assert (
        norm_name("  Foo.MD ") == "foo" and norm_name("a.txt") == "a" and norm_name("a.b") == "a.b"
    )


@pytest.mark.parametrize(
    ("note", "source", "expected"),
    [
        ("a", "x/b.md", "a.md"),
        ("A.md", "x/b.md", "a.md"),
        ("idea", "x/b.md", "Notes/Idea.md"),  # shallowest of two basename matches
        ("idea", "Notes/deep/other.md", "Notes/deep/Idea.md"),  # same folder as the source wins
        ("deep/idea", "a.md", "Notes/deep/Idea.md"),  # trailing part of a path
        ("Notes/Idea", "a.md", "Notes/Idea.md"),  # full path beats the deeper partial match
        ("plan", "a.md", "work/Plan.md"),  # .md over .txt
        ("plan.txt", "a.md", "work/plan.txt"),  # explicit extension picks the txt
        ("nope", "a.md", None),
        ("", "x/b.md", "x/b.md"),  # [[#heading]] is the current note
        ("/a", "x/b.md", "a.md"),
    ],
)
def test_resolve_wikilink(note: str, source: str, expected: str | None) -> None:
    assert resolve_wikilink(note, source, PATHS) == expected


def test_resolve_md_link() -> None:
    assert resolve_md_link("../a.md", "x/b.md", set(PATHS)) == "a.md"
    assert resolve_md_link("b.md#top", "x/c.md", set(PATHS)) == "x/b.md"
    assert resolve_md_link("Notes/Idea.md", "a.md", set(PATHS)) == "Notes/Idea.md"
    assert resolve_md_link("My%20note.md", "a.md", {"My note.md"}) == "My note.md"
    for bad in [
        "https://e.org/a.md",
        "/a.md",
        "#x",
        "",
        "mailto:a@b",
        "../../etc/passwd",
        "nope.md",
    ]:
        assert resolve_md_link(bad, "a.md", set(PATHS)) is None, bad


def test_link_keys() -> None:
    keys = set(link_keys(PATHS))
    assert {"a", "idea", "notes/idea", "deep/idea", "notes/deep/idea", "plan", "work/plan"} <= keys
    assert "nope" not in keys


def test_new_note_path() -> None:
    assert new_note_path("Fresh", "x/b.md") == "x/Fresh.md"
    assert new_note_path("Fresh", "a.md") == "Fresh.md"
    assert new_note_path("sub/Fresh", "x/b.md") == "sub/Fresh.md"
    assert new_note_path("list.txt", "x/b.md") == "x/list.txt"
    for bad in ["", "  ", "../x", ".hidden", "a/../b", "a//b"]:
        assert new_note_path(bad, "a.md") is None, bad


def test_headings() -> None:
    text = "# One\n\ntext\n\n## Two *x*\n\n```\n# not\n```\n\nThree\n=====\n"
    assert [(h.level, h.text, h.line) for h in headings(text)] == [
        (1, "One", 1),
        (2, "Two x", 5),
        (1, "Three", 11),
    ]
    found = find_heading(text, "  two   X ")
    assert found is not None and found.line == 5
    assert find_heading(text, "not") is None
