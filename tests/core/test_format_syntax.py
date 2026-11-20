"""The formatting menu's syntax in the reference parser (PLAN §4.38): highlight, the two allowed
tags, comments. tests/fixtures/format_cases.json is also checked against the editor's grammar
(tools/editor_src/check_sync.mjs)."""

import json
import re
from pathlib import Path

import pytest

from paper_pile.core.formatting import COLORS
from paper_pile.core.parser import format_marks, render_chat_html, render_html

ROOT = Path(__file__).parent.parent.parent
CASES = json.loads((ROOT / "tests" / "fixtures" / "format_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_format_fixture(case: dict[str, object]) -> None:
    want = {k: case[k] for k in ("highlights", "tags", "comments", "line_comments")}
    assert format_marks(str(case["src"])) == want


def test_render_marks_underline_and_colour() -> None:
    html = render_html('a ==hi== <u>u</u> <span style="color:#e03e3e">r</span>')
    assert "<mark>hi</mark>" in html
    assert "<u>u</u>" in html
    assert '<span style="color:#e03e3e">r</span>' in html


def test_other_html_stays_escaped() -> None:
    html = render_html('<script>x</script> <span onclick="y">z</span>')
    assert "<script>" not in html and "<span onclick" not in html
    assert "&lt;script&gt;" in html and "&lt;span onclick" in html


def test_comments_are_never_rendered() -> None:
    html = render_html("plan%%secret%% done // hidden too\n\n// whole line\nnext")
    assert "secret" not in html and "hidden" not in html and "whole line" not in html
    assert "plan" in html and "next" in html


def test_urls_and_code_keep_their_slashes() -> None:
    html = render_html("see https://x.org/a and `a // b`")
    assert "https://x.org/a" in html and "a // b" in html


def test_chat_answers_keep_comment_like_text() -> None:
    assert "x // y" in render_chat_html("x // y") and "%%z%%" in render_chat_html("%%z%%")


def test_editor_palette_matches_python() -> None:
    js = (ROOT / "tools" / "editor_src" / "format.js").read_text(encoding="utf-8")
    pairs = dict(re.findall(r'"(#[0-9a-f]{6})": "(\w+)"', js))
    assert pairs == {code: name for name, code in COLORS.items()}
    css = (ROOT / "paper_pile" / "gui" / "static" / "app.css").read_text(encoding="utf-8")
    for name, code in COLORS.items():
        assert f".pp-fc-{name} {{ color: {code}; }}" in css
