import json
from pathlib import Path

import pytest

from paper_pile.core.links import WikiTarget, parse_wikilink
from paper_pile.core.parser import render_html, wikilinks

FIXTURE = Path(__file__).parent.parent / "fixtures" / "wikilink_cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---- parse_wikilink: the inside of [[...]] -----------------------------------------------


@pytest.mark.parametrize(
    ("inner", "expected"),
    [
        ("note", WikiTarget("note", "", "")),
        ("note|alias", WikiTarget("note", "", "alias")),
        ("note#Heading", WikiTarget("note", "Heading", "")),
        ("note#Heading|alias", WikiTarget("note", "Heading", "alias")),
        ("#Heading", WikiTarget("", "Heading", "")),
        ("  spaced  # head  |  al  ", WikiTarget("spaced", "head", "al")),
        ("a|b|c", WikiTarget("a", "", "b|c")),  # only the first | splits
        ("a#b#c", WikiTarget("a", "b#c", "")),  # only the first # splits
        ("a#b|c#d", WikiTarget("a", "b", "c#d")),  # a # after the | belongs to the alias
        ("a|", WikiTarget("a", "", "")),
        ("a#", WikiTarget("a", "", "")),
        ("folder/sub/note.md", WikiTarget("folder/sub/note.md", "", "")),
    ],
)
def test_parse_wikilink(inner: str, expected: WikiTarget) -> None:
    assert parse_wikilink(inner) == expected


@pytest.mark.parametrize("inner", ["", "   ", "#", "|", "|alias", "#|alias", " # | x "])
def test_parse_wikilink_nothing_to_point_at(inner: str) -> None:
    assert parse_wikilink(inner) is None


def test_display_text() -> None:
    assert WikiTarget("note", "", "").text == "note"
    assert WikiTarget("note", "Intro", "").text == "note > Intro"
    assert WikiTarget("", "Intro", "").text == "Intro"
    assert WikiTarget("note", "Intro", "start here").text == "start here"


# ---- the markdown-it rule: shared fixture (also checked against the editor grammar) -------


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_wikilink_fixture(case: dict[str, object]) -> None:
    found = [
        {"note": w.note, "heading": w.heading, "alias": w.alias}
        for w in wikilinks(str(case["src"]))
    ]
    assert found == case["links"]


# ---- rendering ----------------------------------------------------------------------------


def test_renders_a_marked_up_link_with_its_target() -> None:
    html = render_html("See [[folder/note#Part two|the part]] now.")
    assert (
        '<a class="wikilink" data-note="folder/note" data-heading="Part two">the part</a>' in html
    )


def test_plain_wikilink_shows_the_note_name() -> None:
    assert ">note</a>" in render_html("[[note]]")
    assert ">note &gt; Intro</a>" in render_html("[[note#Intro]]")


def test_wikilink_content_is_escaped() -> None:
    html = render_html("[[<script>alert(1)</script>|<b>x</b>]] and [[a\"b#c'd]]")
    assert "<script>" not in html and "<b>" not in html
    assert "&lt;script&gt;" in html
    assert 'data-note="a&quot;b"' in html


def test_wikilinks_are_not_rendered_inside_code() -> None:
    html = render_html("`[[a]]`\n\n```\n[[b]]\n```\n\n    [[c]]\n")
    assert "wikilink" not in html
    assert "[[a]]" in html and "[[b]]" in html and "[[c]]" in html


def test_a_broken_wikilink_stays_text() -> None:
    for src in ["[[a", "[[a]b]]", "[[]]", "[[a\nb]]"]:
        assert "wikilink" not in render_html(src), src


def test_ordinary_links_and_wikilinks_live_together() -> None:
    html = render_html("[web](https://example.org) and [[note]] and [ref]")
    assert 'href="https://example.org"' in html and 'class="wikilink"' in html


def test_wikilink_inside_table_cell_and_list() -> None:
    html = render_html("| a |\n|---|\n| [[x]] |\n\n- [[y]]\n")
    assert html.count('class="wikilink"') == 2
