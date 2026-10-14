import json
from pathlib import Path

import pytest

from paper_pile.core.parser import front_matter, make_parser, math_spans, render_html

FIXTURE = Path(__file__).parent.parent / "fixtures" / "math_cases.json"
MATH_CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))
FM_CASES = json.loads((FIXTURE.parent / "front_matter_cases.json").read_text(encoding="utf-8"))


# ---- math: the shared fixture (also checked against the editor grammar) -----------------


@pytest.mark.parametrize("case", MATH_CASES, ids=[c["name"] for c in MATH_CASES])
def test_math_fixture(case: dict[str, object]) -> None:
    inline, block = math_spans(str(case["src"]))
    assert inline == case["inline"]
    assert block == case["block"]


def test_dollar_amounts_are_text_not_math() -> None:
    inline, block = math_spans("It costs $5 and $10, or $5.50 and $7.")
    assert inline == [] and block == []
    html = render_html("I paid $5 and $10 today")
    assert "math" not in html and "$5 and $10" in html


def test_real_inline_math_renders_as_a_span() -> None:
    html = render_html("Euler: $e^{i\\pi}+1=0$.")
    assert '<span class="math inline">e^{i\\pi}+1=0</span>' in html


def test_block_math_renders_as_a_div_once() -> None:
    html = render_html("Intro line\n$$\nx^2 + y^2\n$$\nOutro line\n")
    assert html.count('class="math block"') == 1
    assert "x^2 + y^2" in html
    assert "<p>Intro line</p>" in html and "<p>Outro line</p>" in html


def test_math_inside_code_is_left_alone() -> None:
    html = render_html("`$x$` and\n\n```\n$$\ny\n$$\n```\n")
    assert "math" not in html
    assert "<code>$x$</code>" in html


def test_math_content_is_html_escaped() -> None:
    html = render_html("$a<b>c$ and\n\n$$\n<script>alert(1)</script>\n$$\n")
    assert "<script>" not in html and "<b>" not in html
    assert "&lt;script&gt;" in html


# ---- front matter: the shared fixture (also checked against the editor grammar) -----------


@pytest.mark.parametrize("case", FM_CASES, ids=[c["name"] for c in FM_CASES])
def test_front_matter_fixture(case: dict[str, object]) -> None:
    fm = front_matter(str(case["src"]))
    if case["raw"] is None:
        assert fm is None
    else:
        assert fm is not None and fm.raw.strip() == case["raw"]


def test_a_heading_after_front_matter_is_a_heading() -> None:
    assert "<h1>Title</h1>" in render_html("---\nk: v\n---\n# Title\n")


def test_dashes_that_are_not_front_matter_stay_a_rule_or_heading() -> None:
    assert "<h2>Title</h2>" in render_html("Title\n---\n")
    assert "<hr" in render_html("text\n\n---\n\nmore")


# ---- GFM and friends --------------------------------------------------------------------


def test_table() -> None:
    html = render_html("| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n")
    assert "<table>" in html and html.count("<tr>") == 3
    assert "<th>a</th>" in html and "<td>4</td>" in html


def test_task_list() -> None:
    html = render_html("- [ ] todo\n- [x] done\n")
    assert html.count('type="checkbox"') == 2
    assert html.count('checked="checked"') == 1  # only the [x] item
    assert "task-list-item" in html


def test_footnote() -> None:
    html = render_html("Claim[^1].\n\n[^1]: The source.\n")
    assert "footnote-ref" in html and "The source." in html
    assert 'class="footnotes"' in html


def test_strikethrough_and_emphasis() -> None:
    html = render_html("~~gone~~ and **bold** and *it*")
    assert "<s>gone</s>" in html and "<strong>bold</strong>" in html and "<em>it</em>" in html


def test_fenced_code_keeps_language() -> None:
    html = render_html("```python\nprint('hi')\n```\n")
    assert 'class="language-python"' in html


def test_single_newline_is_a_line_break_like_in_the_editor() -> None:
    assert "<br" in render_html("line one\nline two")
    assert "<br" not in make_parser(breaks=False).render("line one\nline two")


# ---- safety -----------------------------------------------------------------------------


def test_raw_html_is_escaped_not_passed_through() -> None:
    html = render_html("<script>alert(1)</script> and <img src=x onerror=alert(1)>")
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html


def test_javascript_links_are_not_linked() -> None:
    html = render_html("[click](javascript:alert(1))")
    assert "href=" not in html


# ---- front matter -----------------------------------------------------------------------


def test_front_matter_is_parsed_and_hidden_from_html() -> None:
    text = "---\ntitle: My note\ntags: [a, b]\nauthor: Ada\n---\n\n# Body\n"
    fm = front_matter(text)
    assert fm is not None and fm.error is None
    assert fm.data == {"title": "My note", "tags": ["a", "b"], "author": "Ada"}
    assert "title" not in render_html(text) and "<h1>Body</h1>" in render_html(text)


def test_no_front_matter() -> None:
    assert front_matter("# Just a heading\n") is None
    assert front_matter("text\n---\nnot: front matter\n---\n") is None  # only valid at the very top
    assert front_matter("") is None


def test_empty_front_matter() -> None:
    fm = front_matter("---\n---\n\nbody")
    assert fm is not None and fm.data == {} and fm.error is None


def test_broken_yaml_reports_an_error_instead_of_raising() -> None:
    fm = front_matter("---\nkey: [unclosed\n---\nbody")
    assert fm is not None and fm.data == {} and fm.error


def test_non_mapping_front_matter() -> None:
    fm = front_matter("---\n- just\n- a list\n---\nbody")
    assert fm is not None and fm.data == {} and "mapping" in (fm.error or "")
