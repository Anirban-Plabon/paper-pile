# ruff: noqa: E501
"""Writes tests/fixtures/paste/<source>_<case>.html and .md.

The HTML is RECONSTRUCTED from the markup shape each chat page is known to produce (KaTeX with an
``application/x-tex`` annotation, code blocks with a header and a Copy button, tables, lists); it is
not a captured clipboard. Replace or add real captures (see `PAPER_PILE_DUMP_PASTE`) whenever
you have them: any ``<source>_<case>.html`` with a matching ``.md`` is picked up by the tests.
Run with: uv run python tools/gen_paste_fixtures.py
"""

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "paste"


def katex(latex: str, visual: str, display: bool = False) -> str:
    inner = (
        '<span class="katex"><span class="katex-mathml"><math xmlns="http://www.w3.org/1998/Math/MathML">'
        f'<semantics><mrow><mi>x</mi></mrow><annotation encoding="application/x-tex">{latex}</annotation>'
        f'</semantics></math></span><span class="katex-html" aria-hidden="true"><span class="base">{visual}</span></span></span>'
    )
    return f'<span class="katex-display">{inner}</span>' if display else inner


CODE = "def area(r):\n    return 3.14159 * r ** 2\n\nprint(area(2))\n"
CODE_HTML = (
    '<span class="hljs-keyword">def</span> <span class="hljs-title function_">area</span>(r):\n'
    '    <span class="hljs-keyword">return</span> <span class="hljs-number">3.14159</span> * r ** <span class="hljs-number">2</span>\n\n'
    '<span class="hljs-built_in">print</span>(area(<span class="hljs-number">2</span>))\n'
)


class Source:
    name = ""

    def p(self, inner: str) -> str:
        return f"<p>{inner}</p>"

    def math_inline(self, latex: str, visual: str) -> str:
        return katex(latex, visual)

    def math_display(self, latex: str, visual: str) -> str:
        return katex(latex, visual, True)

    def code(self, lang: str, html: str) -> str:
        raise NotImplementedError

    def table(self, rows: list[list[str]]) -> str:
        head, *body = rows
        th = "".join(f"<th>{c}</th>" for c in head)
        trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in body)
        return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"

    def li(self, text: str, nested: str = "") -> str:
        return f"<li>{text}{nested}</li>"

    def ul(self, items: str) -> str:
        return f"<ul>{items}</ul>"

    def h(self, level: int, text: str) -> str:
        return f"<h{level}>{text}</h{level}>"

    def wrap(self, body: str) -> str:
        return body


class ChatGPT(Source):
    name = "chatgpt"

    def p(self, inner: str) -> str:
        return f'<p data-start="12" data-end="80">{inner}</p>'

    def code(self, lang: str, html: str) -> str:
        return (
            '<pre><div class="contain-inline-size rounded-md border-[0.5px] border-token-border-medium relative bg-token-sidebar-surface-primary">'
            f'<div class="flex items-center text-token-text-secondary px-4 py-2 text-xs font-sans justify-between h-9 bg-token-sidebar-surface-primary select-none rounded-t-[5px]">{lang}'
            '<div class="flex items-center"><button class="flex gap-1 items-center select-none py-1" aria-label="Copy"><svg width="24"></svg>Copy code</button></div></div>'
            f'<div class="overflow-y-auto p-4" dir="ltr"><code class="!whitespace-pre hljs language-{lang}">{html}</code></div></div></pre>'
        )

    def li(self, text: str, nested: str = "") -> str:
        return f'<li><p data-start="1" data-end="9">{text}</p>{nested}</li>'

    def wrap(self, body: str) -> str:
        return f'<meta charset="utf-8"><div class="markdown prose w-full break-words dark:prose-invert dark"><!--StartFragment-->{body}<!--EndFragment--></div>'


class Claude(Source):
    name = "claude"

    def p(self, inner: str) -> str:
        return f'<p class="whitespace-normal break-words">{inner}</p>'

    def code(self, lang: str, html: str) -> str:
        return (
            '<div class="relative group/copy bg-bg-000/50 border-0.5 border-border-400 rounded-lg">'
            f'<div class="text-text-500 font-small p-3.5 pb-0">{lang}</div>'
            '<div class="sticky opacity-0 group-hover/copy:opacity-100 top-2 py-2 h-12 w-0 float-right"><div class="absolute right-0 h-8 px-2 items-center inline-flex z-10"><button class="inline-flex items-center justify-center relative shrink-0"><span>Copy</span></button></div></div>'
            f'<div><pre class="code-block__code !my-0 !rounded-lg !text-sm !leading-relaxed"><code class="language-{lang}" style="background: none">{html}</code></pre></div></div>'
        )

    def table(self, rows: list[list[str]]) -> str:
        css = "bg-bg-100 min-w-full border-separate border-spacing-0 text-sm leading-[1.88888]"
        inner = super().table(rows).replace("<table>", f'<table class="{css}">')
        return f'<div class="overflow-x-auto w-full px-2 mb-6">{inner}</div>'

    def ul(self, items: str) -> str:
        return f'<ul class="[&:not(:last-child)_ul]:pb-1 [&:not(:last-child)_ol]:pb-1 list-disc">{items}</ul>'

    def wrap(self, body: str) -> str:
        return f'<meta charset="utf-8"><div class="font-claude-response relative leading-[1.65rem]"><div class="grid-cols-1 grid gap-2.5 [&_>_*]:min-w-0 standard-markdown">{body}</div></div>'


class Gemini(Source):
    name = "gemini"

    def p(self, inner: str) -> str:
        return f'<p data-path-to-node="3">{inner}</p>'

    def math_inline(self, latex: str, visual: str) -> str:
        return f'<span class="math-inline" data-math="{latex}">{katex(latex, visual)}</span>'

    def math_display(self, latex: str, visual: str) -> str:
        return f'<div class="math-block" data-math="{latex}">{katex(latex, visual, True)}</div>'

    def code(self, lang: str, html: str) -> str:
        return (
            f'<code-block><div class="code-block ng-star-inserted"><div class="code-block-decoration header-formatted gds-title-s"><span>{lang.capitalize()}</span>'
            '<div class="buttons"><button class="copy-button"><mat-icon>content_copy</mat-icon><span>Copy code</span></button></div></div>'
            f'<div class="formatted-code-block-internal-container"><div class="animated-opacity"><pre class="ng-star-inserted"><code class="code-container formatted" data-test-id="code-content">{html}</code></pre></div></div></div></code-block>'
        )

    def table(self, rows: list[list[str]]) -> str:
        return f'<table-block><div class="table-block-component"><div class="table-content">{super().table(rows)}</div></div></table-block>'

    def ul(self, items: str) -> str:
        return f'<ul data-path-to-node="5">{items}</ul>'

    def li(self, text: str, nested: str = "") -> str:
        return f'<li><p data-path-to-node="5,0,0">{text}</p>{nested}</li>'

    def wrap(self, body: str) -> str:
        return f'<meta charset="utf-8"><div class="markdown markdown-main-panel enable-updated-hr-color" dir="ltr">{body}</div>'


class DeepSeek(Source):
    name = "deepseek"

    def p(self, inner: str) -> str:
        return f'<p class="ds-markdown-paragraph">{inner}</p>'

    def code(self, lang: str, html: str) -> str:
        plain = html
        for tag in (
            '<span class="hljs-keyword">',
            '<span class="hljs-title function_">',
            '<span class="hljs-number">',
            '<span class="hljs-built_in">',
            "</span>",
        ):
            plain = plain.replace(tag, "")
        return (
            '<div class="md-code-block md-code-block-light"><div class="md-code-block-banner-wrap"><div class="md-code-block-banner md-code-block-banner-lite"><div class="_121d384"><div class="d2a24f03">'
            f'<span class="d813de27">{lang}</span></div><div class="efa13877"><div class="ds-icon-button"><span class="code-info-button-text">Copy</span></div>'
            '<div class="ds-icon-button"><span class="code-info-button-text">Download</span></div></div></div></div></div>'
            f"<pre>{plain}</pre></div>"
        )

    def table(self, rows: list[list[str]]) -> str:
        return f'<div class="ds-scroll-area"><div class="ds-scroll-area__gutters"></div>{super().table(rows)}</div>'

    def wrap(self, body: str) -> str:
        return f'<meta charset="utf-8"><div class="ds-markdown">{body}</div>'


TABLE = [["Name", "Qty", "Note"], ["apple", "3", "a_b"], ["pear", "12", "**ripe**"]]
TABLE_MD = (
    "| Name | Qty | Note |\n| --- | --- | --- |\n| apple | 3 | a_b |\n| pear | 12 | **ripe** |"
)


def cases(src: Source) -> dict[str, tuple[str, str]]:
    inline = (
        src.p(
            "The area of a circle is "
            + src.math_inline(r"A = \pi r^2", "A=πr2")
            + ", and energy is "
            + src.math_inline("E = mc^2", "E=mc2")
            + "."
        ),
        "The area of a circle is $A = \\pi r^2$, and energy is $E = mc^2$.",
    )
    display = (
        src.p("Solve the integral:")
        + src.math_display(r"\int_0^1 x\,dx = \frac{1}{2}", "∫01xdx=12")
        + src.p("Then multiple lines:")
        + src.math_display("\\begin{aligned}\n a &= b \\\\\n c &= d\n\\end{aligned}", "a=bc=d"),
        "Solve the integral:\n\n$$\\int_0^1 x\\,dx = \\frac{1}{2}$$\n\nThen multiple lines:\n\n"
        "$$\n\\begin{aligned}\n a &= b \\\\\n c &= d\n\\end{aligned}\n$$",
    )
    code = (
        src.p("Here is a function:") + src.code("python", CODE_HTML),
        "Here is a function:\n\n```python\n" + CODE.rstrip("\n") + "\n```",
    )
    table = (
        src.p("Fruit stock:")
        + src.table([[c.replace("**ripe**", "<strong>ripe</strong>") for c in r] for r in TABLE]),
        "Fruit stock:\n\n" + TABLE_MD,
    )
    nested = (
        src.ul(
            src.li(
                "First <strong>item</strong>",
                src.ul(
                    src.li("Second level", src.ul(src.li("Third level"))) + src.li("Another second")
                ),
            )
            + src.li("Last <em>item</em>")
        ),
        "- First **item**\n  - Second level\n    - Third level\n  - Another second\n- Last *item*",
    )
    mixed = (
        src.h(2, "Circle facts")
        + src.p("Its area is " + src.math_inline(r"\pi r^2", "πr2") + " and:")
        + src.ul(
            src.li("radius " + src.math_inline("r", "r"))
            + src.li("diameter " + src.math_inline("2r", "2r"))
        )
        + src.math_display(r"C = 2\pi r", "C=2πr")
        + src.code("python", CODE_HTML)
        + src.table([["r", "area"], ["1", "3.14"]]),
        "## Circle facts\n\nIts area is $\\pi r^2$ and:\n\n- radius $r$\n- diameter $2r$\n\n$$C = 2\\pi r$$\n\n"
        "```python\n" + CODE.rstrip("\n") + "\n```\n\n| r | area |\n| --- | --- |\n| 1 | 3.14 |",
    )
    return {
        "inline_math": inline,
        "display_math": display,
        "code": code,
        "table": table,
        "nested_list": nested,
        "mixed": mixed,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for src in (ChatGPT(), Claude(), Gemini(), DeepSeek()):
        for name, (html, md) in cases(src).items():
            (OUT / f"{src.name}_{name}.html").write_text(src.wrap(html), encoding="utf-8")
            (OUT / f"{src.name}_{name}.md").write_text(md + "\n", encoding="utf-8")
    print(f"wrote {len(list(OUT.glob('*.html')))} fixtures to {OUT}")


if __name__ == "__main__":
    main()
