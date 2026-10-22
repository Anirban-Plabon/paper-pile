import json
from pathlib import Path

import pytest

from paper_pile.core.parser import inline_tags, note_tags, render_html
from paper_pile.core.tags import clean_tag, matches, norm_tag, property_tags, unique

FIXTURE = Path(__file__).parent.parent / "fixtures" / "tag_cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_inline_tag_fixture(case: dict[str, object]) -> None:
    assert inline_tags(str(case["src"])) == case["tags"]


def test_property_tags_list_string_and_junk() -> None:
    assert property_tags({"tags": ["a", "#b", "c/d", "  e "]}) == ["a", "b", "c/d", "e"]
    assert property_tags({"tags": "one, two three"}) == ["one", "two", "three"]
    assert property_tags({"tags": ["123", "", None, "ok", "bad tag"]}) == ["ok"]
    assert property_tags({"tags": 5}) == []
    assert property_tags({}) == []


def test_note_tags_property_first_then_inline_once_each() -> None:
    text = "---\ntags: [Work, idea]\n---\nSee #work and #new/sub, #IDEA.\n"
    assert note_tags(text) == ["Work", "idea", "new/sub"]


def test_norm_match_and_unique() -> None:
    assert norm_tag("#Work/") == "work"
    assert matches("work/x", "Work") and matches("WORK", "work")
    assert not matches("workshop", "work")
    assert unique(["A", "a", "b"]) == ["A", "b"]
    assert clean_tag("#ok") == "ok" and clean_tag("no space") == ""


def test_render_html_marks_tags() -> None:
    assert '<a class="tag" data-tag="t">#t</a>' in render_html("x #t")
    assert "tag" not in render_html("`#t`")
