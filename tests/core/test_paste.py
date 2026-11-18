# ruff: noqa: E501  (clipboard HTML samples)
from pathlib import Path

import pytest

from paper_pile.core.paste import html_to_md, needs_own_lines, normalize, smart_paste

FIXTURES = Path(__file__).parent.parent / "fixtures" / "paste"
CASES = sorted(p.stem for p in FIXTURES.glob("*.html"))


def test_there_are_fixtures_for_every_source_and_case() -> None:
    sources = {c.split("_", 1)[0] for c in CASES}
    cases = {c.split("_", 1)[1] for c in CASES}
    assert {"chatgpt", "claude", "gemini", "deepseek"} <= sources
    assert {"inline_math", "display_math", "code", "table", "nested_list", "mixed"} <= cases


@pytest.mark.parametrize("name", CASES)
def test_clipboard_html_becomes_the_expected_markdown(name: str) -> None:
    html = (FIXTURES / f"{name}.html").read_text(encoding="utf-8")
    expected = (FIXTURES / f"{name}.md").read_text(encoding="utf-8").strip("\n")
    assert html_to_md(html).strip("\n") == expected
    assert smart_paste(html, "plain fallback text").strip("\n") == expected


# ---- details --------------------------------------------------------------------------------


def test_math_visual_duplicate_is_dropped() -> None:
    html = (
        '<p>x <span class="katex"><span class="katex-mathml"><math><semantics><mi>a</mi>'
        '<annotation encoding="application/x-tex">a^2</annotation></semantics></math></span>'
        '<span class="katex-html" aria-hidden="true">a2 DUPLICATE</span></span> y</p>'
    )
    assert html_to_md(html) == "x $a^2$ y"


def test_mathjax_scripts_and_data_math() -> None:
    html = (
        '<p>a <script type="math/tex">x_1</script> b '
        '<script type="math/tex; mode=display">y^2</script></p>'
    )
    assert html_to_md(html) == "a $x_1$ b\n\n$$y^2$$"
    assert html_to_md('<p><span class="math-inline" data-math="z">z</span></p>') == "$z$"


def test_math_without_a_tex_source_falls_back_to_its_text() -> None:
    html = '<p>v <span class="katex"><span class="katex-html">1+1</span></span> w</p>'
    assert html_to_md(html) == "v 1+1 w"


def test_code_block_language_from_class_or_header() -> None:
    assert html_to_md('<pre><code class="language-rust">fn main() {}\n</code></pre>') == (
        "```rust\nfn main() {}\n```"
    )
    html = "<div><div><span>JavaScript</span><button>Copy</button></div><pre>let a = 1;</pre></div>"
    assert html_to_md(html) == "```javascript\nlet a = 1;\n```"
    assert html_to_md("<pre>no language\n  indented</pre>") == "```\nno language\n  indented\n```"


def test_code_containing_backticks_gets_a_longer_fence() -> None:
    out = html_to_md("<pre><code>```\ninner\n```</code></pre>")
    assert out.startswith("````") and out.endswith("````") and "inner" in out


def test_interface_text_is_removed() -> None:
    html = (
        "<p>Answer</p><button>Copy</button><div class='copy-wrapper'>Copied!</div>"
        '<a data-testid="webpage-citation-pill" href="https://e.org">e.org</a><p>End</p>'
    )
    assert html_to_md(html) == "Answer\n\nEnd"


def test_ordinary_html_keeps_links_images_quotes_and_rules() -> None:
    html = (
        '<h1>T</h1><p>see <a href="https://e.org/x">the page</a> and '
        '<img src="https://e.org/i.png" alt="pic"></p>'
        "<blockquote><p>quoted</p></blockquote><hr><p>snake_case and 2*3</p>"
    )
    out = html_to_md(html)
    assert "# T" in out and "[the page](https://e.org/x)" in out
    assert "![pic](https://e.org/i.png)" in out
    assert "> quoted" in out and "snake_case" in out and "---" in out


def test_task_list_boxes() -> None:
    html = (
        '<ul><li><input type="checkbox" checked> done</li>'
        '<li><input type="checkbox"> todo</li></ul>'
    )
    assert html_to_md(html) == "- [x] done\n- [ ] todo"


def test_line_breaks_become_newlines() -> None:
    assert html_to_md("<p>one<br>two</p>") == "one\ntwo"


# ---- plain text -----------------------------------------------------------------------------


def test_normalize_math_delimiters() -> None:
    assert normalize(r"Euler \( e^{i\pi}+1=0 \) done") == "Euler $e^{i\\pi}+1=0$ done"
    assert normalize("a\n\\[\nx^2\n\\]\nb") == "a\n$$x^2$$\nb"
    assert normalize("\\[\nline1\nline2\n\\]") == "$$\nline1\nline2\n$$"
    assert normalize(r"\(a\) and \(b\)") == "$a$ and $b$"


def test_normalize_leaves_code_alone() -> None:
    text = "use `\\(x\\)` here\n```\n\\[ y \\]\n\\( z \\)\n```\nand \\( w \\)"
    assert normalize(text) == "use `\\(x\\)` here\n```\n\\[ y \\]\n\\( z \\)\n```\nand $w$"
    assert normalize("~~~\n\\(a\\)\n~~~") == "~~~\n\\(a\\)\n~~~"


def test_normalize_plain_text_is_unchanged() -> None:
    for text in ["", "hello", "a $b$ c", "1 \\ 2", "price (5) [6]", "  indented\n\ttab"]:
        assert normalize(text) == text


# ---- deciding -------------------------------------------------------------------------------


def test_smart_paste_prefers_structured_html() -> None:
    assert smart_paste("<ul><li>a</li><li>b</li></ul>", "a\nb") == "- a\n- b"


def test_smart_paste_keeps_exact_text_for_plain_wrappers() -> None:
    html = "<meta charset='utf-8'><div><span style='color:red'>  indented code</span></div>"
    assert smart_paste(html, "  indented code") == "  indented code"
    assert smart_paste("", "x \\(y\\)") == "x $y$"
    assert smart_paste("<p></p>", "fallback") == "fallback"


# ---- rendering audit (P35): shapes that broke tables, lists and math --------------------------


def _katex(tex: str, display: bool = False) -> str:
    inner = (
        '<span class="katex"><span class="katex-mathml"><math><semantics><mi>x</mi>'
        f'<annotation encoding="application/x-tex">{tex}</annotation></semantics></math></span>'
        '<span class="katex-html" aria-hidden="true">VISUAL</span></span>'
    )
    return f'<span class="katex-display">{inner}</span>' if display else inner


def _table(head: str, body: str) -> str:
    return f"<table><thead><tr>{head}</tr></thead><tbody><tr>{body}</tr></tbody></table>"


def test_table_without_header_cells_uses_its_first_row_as_header() -> None:
    html = "<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>"
    assert html_to_md(html) == "| a | b |\n| --- | --- |\n| 1 | 2 |"


def test_pipes_in_cells_are_escaped_also_in_math_and_code() -> None:
    html = _table(
        "<th>a</th><th>b</th><th>c</th>",
        f"<td>x | y</td><td>{_katex('|x|')}</td><td><code>a|b</code></td>",
    )
    assert html_to_md(html).split("\n")[2] == r"| x \| y | $\|x\|$ | `a\|b` |"


def test_cells_with_blocks_stay_on_one_line() -> None:
    html = _table(
        "<th>a</th><th>b</th>",
        f"<td><p>one</p><p>two<br>three</p></td><td>{_katex('a', True)}<pre><code>x\ny</code></pre></td>",
    )
    assert html_to_md(html).split("\n")[2] == "| one two three | $$a$$ `x y` |"


def test_ragged_rows_and_colspan_keep_the_column_count() -> None:
    html = "<table><tr><th colspan=2>ab</th><th>c</th></tr><tr><td>1</td></tr></table>"
    assert html_to_md(html) == "| ab |  | c |\n| --- | --- | --- |\n| 1 |  |  |"


def test_cell_alignment_is_kept() -> None:
    html = _table(
        '<th align="right">n</th><th style="text-align: center">m</th>', "<td>1</td><td>2</td>"
    )
    assert html_to_md(html).split("\n")[1] == "| ---: | :---: |"


def test_google_docs_wrapper_does_not_bold_the_whole_table() -> None:
    html = (
        '<meta charset="utf-8"><b style="font-weight:normal;" id="docs-internal-guid-1"><div dir="ltr">'
        "<table><tbody><tr><td><p><span>Name</span></p></td><td><p><span>Age</span></p></td></tr>"
        "<tr><td><p><span>Bob</span></p></td><td><p><span>3</span></p></td></tr></tbody></table></div></b>"
    )
    assert html_to_md(html) == "| Name | Age |\n| --- | --- |\n| Bob | 3 |"


def test_styled_spans_become_bold_italic_strike() -> None:
    html = (
        '<p><span style="font-weight:700">b</span> <span style="font-style:italic">i</span> '
        '<span style="text-decoration:line-through">s</span></p>'
    )
    assert html_to_md(html) == "**b** *i* ~~s~~"


def test_display_math_and_code_stay_inside_list_items_and_quotes() -> None:
    html = (
        f"<ol><li><p>Step:</p>{_katex('x^2', True)}</li><li><p>Run:</p>"
        "<pre><code class='language-sh'>ls\ncd x</code></pre></li></ol>"
    )
    assert html_to_md(html) == "1. Step:\n\n   $$x^2$$\n2. Run:\n\n   ```sh\n   ls\n   cd x\n   ```"
    quote = f"<blockquote><p>q</p>{_katex('a', True)}<pre><code>x\n\ny</code></pre></blockquote>"
    assert html_to_md(quote) == "> q\n>\n> $$a$$\n>\n> ```\n> x\n>\n> y\n> ```"


def test_wikipedia_mathml_becomes_tex_once() -> None:
    html = (
        '<p>E <span class="mwe-math-element"><span class="mwe-math-mathml-inline" style="display: none;">'
        '<math alttext="{\\displaystyle E=mc^{2}}"><semantics><mrow><mi>E</mi></mrow>'
        '<annotation encoding="application/x-tex">{\\displaystyle E=mc^{2}}</annotation></semantics>'
        '</math></span><img src="x.svg" class="mwe-math-fallback-image-inline" alt="{\\displaystyle E=mc^{2}}">'
        "</span> holds.</p>"
    )
    assert html_to_md(html) == "E $E=mc^{2}$ holds."


def test_mathml_without_tex_is_read_as_latex() -> None:
    html = (
        '<p>v <mjx-container class="MathJax" jax="CHTML"><mjx-math>VISUAL</mjx-math><mjx-assistive-mml>'
        "<math><mfrac><mi>a</mi><msup><mi>b</mi><mn>2</mn></msup></mfrac><mo>≤</mo><msqrt><mi>x</mi>"
        "</msqrt></math></mjx-assistive-mml></mjx-container> w</p>"
    )
    assert html_to_md(html) == r"v $\frac{a}{{b}^{2}} \le \sqrt{x}$ w"
    assert html_to_md('<p><math alttext="x^2"><mi>x</mi></math></p>') == "$x^2$"


def test_mathjax2_rendered_copy_is_dropped() -> None:
    html = (
        '<p>a <span class="MathJax_Preview"></span><span class="MathJax">x1 VISUAL</span>'
        '<script type="math/tex">x_1</script> b</p>'
    )
    assert html_to_md(html) == "a $x_1$ b"


def test_blank_lines_inside_display_math_are_removed() -> None:
    assert html_to_md(f"<p>{_katex('a\\\\\n\n b', True)}</p>") == "$$\na\\\\\nb\n$$"
    assert normalize("\\[\na\n\nb\n\\]") == "$$\na\nb\n$$"


def test_normalize_leaves_tex_line_break_spacing_alone() -> None:
    text = r"$$\begin{bmatrix}1\\[4pt]2\end{bmatrix}$$ and \(x\) then \[y\]"
    assert normalize(text) == r"$$\begin{bmatrix}1\\[4pt]2\end{bmatrix}$$ and $x$ then $$y$$"


def test_tables_and_blocks_at_the_edges_need_their_own_lines() -> None:
    assert needs_own_lines("Here:\n\n| a |\n| --- |\n| 1 |")  # ends in a table
    assert needs_own_lines("| a |\n| --- |\n| 1 |\n\nafter")  # starts with one
    assert needs_own_lines("```\nx\n```") and needs_own_lines("$$x$$") and needs_own_lines("# H")
    for inline in ("hello", "a $x$ b", "- item", "> quote", "p1\n\np2"):
        assert not needs_own_lines(inline)
