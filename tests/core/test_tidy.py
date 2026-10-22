from pathlib import Path

import pytest

from paper_pile.core.parser import render_html
from paper_pile.core.tidy import tidy

REPO = Path(__file__).resolve().parents[2]

CASES = {
    "blank runs": ("a\n\n\n\nb\n\n\n", "a\n\nb\n"),
    "leading blanks": ("\n\n\n# H\n", "# H\n"),
    "trailing spaces": ("a   \t\n\nb ", "a\n\nb\n"),
    "blocks get air": (
        "# Title\ntext\n## Two\n- a\n- b\n\n\n\nend\n---\nafter",
        "# Title\n\ntext\n\n## Two\n\n- a\n- b\n\n## end\n\nafter\n",  # end/--- is a heading
    ),
    "heading space": ("#   Big\n\n##\tSmall", "# Big\n\n## Small\n"),
    "rules": ("a\n\n***\n\nb\n\n_ _ _\n", "a\n\n---\n\nb\n\n---\n"),
    "lazy callout line": (
        "> **Note:** hi\n> two\nlazy\n> three\n\nout",
        "> **Note:** hi\n> two\n> lazy\n> three\n\nout\n",
    ),
    "lazy list lines": (
        "- [ ] one\n- [ ] two\nlazy\nmore\n\nout",
        "- [ ] one\n- [ ] two\n  lazy\n  more\n\nout\n",
    ),
    "nested lazy": ("1. one\n   - inner\nlazy", "1. one\n   - inner\n     lazy\n"),
    "loose list keeps one blank": ("- a\n\n\n\n- b\n", "- a\n\n- b\n"),
    "code untouched": (
        "text\n```py\nx = 1   \n\n\n\ny = 2\n```\nafter",
        "text\n\n```py\nx = 1   \n\n\n\ny = 2\n```\n\nafter\n",
    ),
    "math untouched": ("a\n$$\nx^2  \n\n$$\nb", None),
    "front matter kept tight": (
        "---\ntitle: T\n---\n# H\ntext",
        "---\ntitle: T\n---\n# H\n\ntext\n",
    ),
    "front matter keeps its gap": (
        "---\ntitle: T\n---\n\n\n\ntext",
        "---\ntitle: T\n---\n\ntext\n",
    ),
    "setext headings": ("Big\n===\nsmall\n---\ntext", "# Big\n\n## small\n\ntext\n"),
    "hard break kept": ("one  \ntwo   \n\nthree  ", "one  \ntwo\n\nthree\n"),
    "table aligned": ("|a|bb|\n|-|-|\n|1|2|\ntext", None),
    "link definitions kept": (
        "see [x]\n\n\n[x]: http://e.com  \n",
        "see [x]\n\n[x]: http://e.com\n",
    ),
    "footnotes kept": ("text[^1]\n\n\n\n[^1]: note\n", "text[^1]\n\n[^1]: note\n"),
    "empty": ("", ""),
    "only blanks": ("\n\n \n", ""),
}


@pytest.mark.parametrize("name", CASES)
def test_cases(name: str) -> None:
    text, expected = CASES[name]
    out = tidy(text)
    if expected is not None:
        assert out == expected
    assert tidy(out) == out  # idempotent
    assert render_html(out) == render_html(text)  # means the same


def test_table_is_aligned_but_never_loses_cells() -> None:
    assert tidy("|a|bb|\n|-|-|\n|1|2|\n") == "| a   | bb  |\n| --- | --- |\n| 1   | 2   |\n"
    extra = "|a|b|\n|-|-|\n|1|2|3|\n"
    assert tidy(extra) == extra  # a third cell would be dropped by re-formatting: left alone


def test_code_and_math_bytes_are_kept() -> None:
    text = "```\n  a  \n\n\n```\n$$\n b \n$$\n"
    out = tidy(text)
    assert "```\n  a  \n\n\n```" in out and "$$\n b \n$$" in out


def test_crlf_is_kept() -> None:
    assert tidy("a\r\n\r\n\r\nb\r\n") == "a\r\n\r\nb\r\n"


def _corpus() -> list[Path]:
    files = sorted((REPO / "tests" / "fixtures").rglob("*.md")) + sorted(
        (REPO / "docs").glob("*.md")
    )
    return [f for f in files if f.is_file()]


@pytest.mark.parametrize("path", _corpus(), ids=lambda p: p.name)
def test_real_notes_mean_the_same_after_tidying(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    out = tidy(text)
    assert render_html(out) == render_html(text)
    assert tidy(out) == out
