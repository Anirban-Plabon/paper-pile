from pathlib import Path

import pytest

from paper_pile.core.paste import html_to_md, normalize, smart_paste

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
