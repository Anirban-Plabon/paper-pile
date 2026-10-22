import json
from pathlib import Path

import pytest

from paper_pile.core.pagebreak import PAGE_BREAK, effective, is_break_line
from paper_pile.core.parser import page_breaks, render_html

FIXTURE = Path(__file__).parent.parent / "fixtures" / "pagebreak_cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_page_break_fixture(case: dict[str, object]) -> None:
    got = [{"line": b.line, "effective": b.effective} for b in page_breaks(str(case["src"]))]
    assert got == case["breaks"]


@pytest.mark.parametrize(
    "line",
    [
        PAGE_BREAK,
        '<div style="break-after: page;"></div>',
        "<div class='page-break'></div>",
        '   <div style="PAGE-BREAK-AFTER:ALWAYS"></div>   ',
    ],
)
def test_break_line_forms(line: str) -> None:
    assert is_break_line(line)


@pytest.mark.parametrize(
    "line",
    [
        "    " + PAGE_BREAK,  # indented code
        "\t" + PAGE_BREAK,
        "<div style=\"page-break-after: always;'></div>",  # quotes do not match
        '<div style="page-break-after: always;">',
        '<div style="page-break-after: always;"></div> x',
        '<div class="page-break other"></div>',
        "<hr>",
    ],
)
def test_not_break_lines(line: str) -> None:
    assert not is_break_line(line)


def test_effective_needs_content_on_both_sides_and_collapses_runs() -> None:
    assert effective([True, False, True, True, False, True]) == [
        False,
        False,
        True,
        False,
        False,
        False,
    ]
    assert effective([False, True, False, True, False]) == [False, True, False, True, False]
    assert effective([]) == []


def test_render_drops_breaks_that_do_nothing() -> None:
    src = f"{PAGE_BREAK}\n\na\n\n{PAGE_BREAK}\n\n{PAGE_BREAK}\n\nb\n\n{PAGE_BREAK}\n"
    assert render_html(src) == '<p>a</p>\n<div class="pp-page-break"></div>\n<p>b</p>\n'


def test_other_raw_html_is_still_escaped() -> None:
    assert render_html('a\n\n<div style="color: red"></div>\n\nb').count("&lt;div") == 1
