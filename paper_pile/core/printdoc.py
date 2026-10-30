"""The print layout's document (PLAN §4.17): a note rendered as one HTML page that the paginator
(``tools/editor_src/paginate.js``) lays out on sheets of paper. The same page makes the PDF and the
editor's page lines, so both always agree.

What it adds to :func:`paper_pile.core.parser.render_html`:

* every block carries the 1-based source line it starts on (``data-line``), and a fenced or
  indented code block the line of its first code line (``data-code-line``), so a page that starts
  inside a block can be traced back to its line in the note. Inside a paragraph each ``<br>`` is
  one source line (the parser renders single newlines as breaks);
* the editor's look where it differs from plain HTML: callouts (a quote opening with a bold label),
  ``![alt|300](…)`` image widths, ``![[note]]`` embeds on a line of their own;
* empty lines are space, as in the editor: between two blocks one empty line is the usual gap,
  every further one becomes a spacer one line tall (``pp-blank``, with its source line). Markdown
  would merge them; on paper they let the user push text down (and onto the next page) with Enter;
* images are served by the app (``/_pp/asset``); math stays TeX and diagrams code: the page's
  script typesets them with the editor's own code.

Front matter is not printed. Nothing here touches the UI.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html import escape
from urllib.parse import quote, unquote

from markdown_it.common.utils import escapeHtml
from markdown_it.renderer import RendererProtocol
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict

from paper_pile.core.parser import make_parser


@dataclass(frozen=True, slots=True)
class Paper:
    name: str
    width_mm: float
    height_mm: float


PAPERS = {"A4": Paper("A4", 210, 297), "Letter": Paper("Letter", 215.9, 279.4)}
MARGIN_MM = 20


def paper(name: str) -> Paper:
    """A paper size by its setting value (A4 for anything unknown)."""
    return PAPERS.get(name, PAPERS["A4"])


def text_width_mm(name: str) -> float:
    """How wide the text is on that paper: the editor's column in page view."""
    return paper(name).width_mm - 2 * MARGIN_MM


@dataclass(frozen=True, slots=True)
class PrintStyle:
    """The editor's type settings, so the paper looks like the editor."""

    font_family: str = "monospace"
    code_font: str = "monospace"
    font_size: int = 14  # px
    line_height: float = 1.6
    accent_rgb: tuple[int, int, int] = (59, 130, 246)  # the light theme's accent


@dataclass(frozen=True, slots=True)
class EmbedHtml:
    title: str
    html: str  # safe HTML of the embedded note ("" if it could not be shown)
    message: str = ""


# `![[note]]`, `![[note#heading]]` -> what to show (core/embed.py), given the embed's raw target
Embedder = Callable[[str, str], EmbedHtml]

CALLOUT_TYPES = {
    **dict.fromkeys(("tip", "success", "done", "hint"), "ok"),
    **dict.fromkeys(("warning", "caution", "attention", "important"), "warn"),
    **dict.fromkeys(("danger", "error", "bug", "failure"), "bad"),
}
_CALLOUT = re.compile(r"^\s*\*\*([^*\n]+?):?\*\*")
# `[!note]` / `[!tip]- Title`: the Obsidian/GitHub header, drawn like the bold label
_CALLOUT_HEADER = re.compile(r"^\[!([A-Za-z][\w-]*)\][-+]?[ \t]*")
_EMBED_LINE = re.compile(r"^!\[\[([^\[\]\n]+)\]\]$")
_SIZED_ALT = re.compile(r"^(.*?)\|\s*(\d+)\s*$", re.S)
_REMOTE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.I)
_CSS_UNSAFE = re.compile(r"[<>{};\\]")


def _render_math_block(
    self: RendererProtocol,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    tok = tokens[idx]
    line = tok.map[0] + 1 if tok.map else 0
    return f'<div class="math block" data-line="{line}">{escapeHtml(tok.content.strip())}</div>\n'


_PARSER = make_parser()
_PARSER.add_render_rule("math_block", _render_math_block)


def _sheet_css(p: Paper, style: PrintStyle) -> str:
    font = _CSS_UNSAFE.sub("", style.font_family) or "monospace"
    code = _CSS_UNSAFE.sub("", style.code_font) or "monospace"
    rgb = ", ".join(str(max(0, min(255, int(c)))) for c in style.accent_rgb)
    return (
        f":root {{ --pp-paper-w: {p.width_mm}mm; --pp-paper-h: {p.height_mm}mm;"
        f" --pp-margin: {MARGIN_MM}mm; --pp-font: {font}; --pp-code-font: {code};"
        f" --pp-size: {int(style.font_size)}px; --pp-lh: {float(style.line_height)};"
        f" --pp-accent: rgb({rgb}); --pp-accent-rgb: {rgb}; }}\n"
        f"@page {{ size: {p.width_mm}mm {p.height_mm}mm; margin: 0; }}\n"
    )


def _asset_url(note: str, src: str) -> str:
    return f"/_pp/asset?note={quote(note, safe='')}&path={quote(unquote(src), safe='')}"


def _mark_lines(tokens: list[Token]) -> None:
    """Every block with a source position gets ``data-line`` (its first line, 1-based)."""
    for tok in tokens:
        if not tok.map or tok.nesting < 0 or tok.type in {"inline", "front_matter"}:
            continue
        tok.attrSet("data-line", str(tok.map[0] + 1))
        if tok.type == "fence":
            tok.attrSet("data-code-line", str(tok.map[0] + 2))
        elif tok.type == "code_block":
            tok.attrSet("data-code-line", str(tok.map[0] + 1))


def _callouts(tokens: list[Token]) -> None:
    """A quote whose first line opens with a bold label (or a ``[!note]`` header) is drawn as a
    callout card."""
    for i, tok in enumerate(tokens):
        if tok.type != "blockquote_open" or i + 2 >= len(tokens):
            continue
        inline = tokens[i + 2]
        if tokens[i + 1].type != "paragraph_open" or inline.type != "inline":
            continue
        m = _CALLOUT.match(inline.content) or _callout_header(inline)
        if m:
            kind = CALLOUT_TYPES.get(m.group(1).strip().lower(), "")
            tok.attrJoin("class", "pp-callout" + (f" pp-callout-{kind}" if kind else ""))


def _callout_header(inline: Token) -> re.Match[str] | None:
    """``[!note] Title`` -> a bold ``Note:`` (or the bold title), like the editor shows it."""
    children = inline.children or []
    if not children or children[0].type != "text":
        return None
    m = _CALLOUT_HEADER.match(children[0].content)
    if not m:
        return None
    title = children[0].content[m.end() :].strip()
    label = title or m.group(1)[0].upper() + m.group(1)[1:].lower() + ":"
    text = Token("text", "", 0, content=label)
    children[0:1] = [Token("strong_open", "strong", 1), text, Token("strong_close", "strong", -1)]
    return m


def _images(tokens: list[Token], note: str) -> None:
    """Images stored in the vault are served by the app; ``alt|300`` sets the width."""
    for tok in tokens:
        for child in tok.children or []:
            if child.type != "image":
                continue
            src = str(child.attrGet("src") or "")
            if src and not _REMOTE.match(src):
                child.attrSet("src", _asset_url(note, src))
            sized = _SIZED_ALT.match(child.content)
            if sized:
                child.children = [Token("text", "", 0, content=sized.group(1))]
                child.attrSet("style", f"width: {int(sized.group(2))}px")


def _embeds(tokens: list[Token], embedder: Embedder | None) -> list[Token]:
    """A paragraph that is only ``![[note]]`` shows that note, as the editor does (the three
    paragraph tokens become one block of HTML)."""
    if embedder is None:
        return tokens
    out: list[Token] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        m = None
        if tok.type == "paragraph_open" and i + 2 < len(tokens) and tokens[i + 1].type == "inline":
            m = _EMBED_LINE.match(tokens[i + 1].content.strip())
        if m is None:
            out.append(tok)
            i += 1
            continue
        target, _, heading = m.group(1).partition("#")
        shown = embedder(target.split("|", 1)[0].strip(), heading.strip())
        body = shown.html or f'<p class="pp-embed-missing">{escape(shown.message)}</p>'
        block = Token("html_block", "", 0, map=tok.map, block=True)
        block.content = (
            f'<div class="pp-embed" data-line="{tok.attrGet("data-line") or 0}">'
            f'<div class="pp-embed-title">{escape(shown.title)}</div>'
            f'<div class="pp-embed-body">{body}</div></div>\n'
        )
        out.append(block)
        i += 3
    return out


def _spacers(tokens: list[Token], lines: list[str]) -> list[Token]:
    """A spacer for every empty line beyond the first in front of each top-level block (all of them
    in front of the first block)."""
    out: list[Token] = []
    first = True
    for tok in tokens:
        if tok.level == 0 and tok.nesting >= 0 and tok.map and tok.type != "front_matter":
            start = tok.map[0]
            empty = 0
            while start - empty - 1 >= 0 and not lines[start - empty - 1].strip():
                empty += 1
            for n in range(start - empty + (0 if first else 1), start):
                spacer = Token("html_block", "", 0, block=True)
                spacer.content = f'<div class="pp-blank" data-line="{n + 1}"></div>\n'
                out.append(spacer)
            first = False
        out.append(tok)
    return out


def render_print_body(text: str, note: str, embedder: Embedder | None = None) -> str:
    """The note's blocks as HTML with source lines (no page around them)."""
    env: dict[str, object] = {}
    tokens = _PARSER.parse(text, env)
    _mark_lines(tokens)
    _callouts(tokens)
    _images(tokens, note)
    # the parser escapes the note's own HTML: the only raw HTML here is what _embeds writes
    tokens = _embeds(tokens, embedder)
    tokens = _spacers(tokens, text.split("\n"))
    return str(_PARSER.renderer.render(tokens, _PARSER.options, env))


@dataclass(frozen=True, slots=True)
class PrintAssets:
    """URLs of the stylesheets and the script the page loads (served by the app)."""

    katex_css: str
    print_css: str
    script: str


def print_page(
    text: str,
    note: str,
    *,
    title: str,
    paper_name: str,
    style: PrintStyle,
    assets: PrintAssets,
    embedder: Embedder | None = None,
) -> str:
    """The whole page: the note's blocks in ``#pp-source``, which the script moves onto sheets."""
    body = render_print_body(text, note, embedder)
    return (
        '<!doctype html>\n<html>\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n"
        f'<link rel="stylesheet" href="{escape(assets.katex_css)}">\n'
        f'<link rel="stylesheet" href="{escape(assets.print_css)}">\n'
        f"<style>{_sheet_css(paper(paper_name), style)}</style>\n"
        f'<script type="module" src="{escape(assets.script)}"></script>\n'
        '</head>\n<body class="pp-print">\n'
        f'<main id="pp-source">\n{body}</main>\n</body>\n</html>\n'
    )
