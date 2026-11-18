"""Smart Paste: turn what the clipboard holds into clean markdown (PLAN §4.10).

* ``html_to_md``: HTML from a web page or an AI chat (ChatGPT, Claude, Gemini, DeepSeek, ...),
  Wikipedia, Google Docs or Word -> markdown. Rendered math (KaTeX / MathJax / MathML) goes back
  to ``$..$`` / ``$$..$$``, code blocks become fenced blocks with their language, tables stay
  tables (a header row, one line per row, ``|`` escaped), math and code inside a list item or a
  quote stay inside it, and the chat page's own interface (Copy buttons, language labels,
  citation chips) is dropped.
* ``normalize``: plain text with ``\\( .. \\)`` / ``\\[ .. \\]`` math delimiters becomes
  ``$..$`` / ``$$..$$``, never touching code.
* ``smart_paste``: picks between the two.
"""

import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag
from markdownify import MarkdownConverter

from paper_pile.core.parser import parse

# interface text of chat pages that is not content
_JUNK_TEXT = {"copy", "copy code", "copied!", "copied", "edit", "download", "run", "share", "retry"}
_JUNK_CLASS = re.compile(
    r"copy|toolbar|citation|banner|decoration|code-info|sr-only|visually-hidden", re.I
)
_SEMANTIC = re.compile(
    r"<\s*(p|h[1-6]|ul|ol|li|table|pre|blockquote|strong|b|em|i|a|img|code|del|s|hr)\b|katex|math",
    re.I,
)
_TOKEN = "\x00{}\x00"
_TOKEN_RE = re.compile(r"\x00(\d+)\x00")
_BLOCK_TAGS = [
    "p", "div", "table", "ul", "ol", "li", "pre", "blockquote", "hr", "section", "article",
    "h1", "h2", "h3", "h4", "h5", "h6",
]  # fmt: skip


@dataclass(frozen=True, slots=True)
class _Piece:
    """A formula or a code block taken out of the HTML before conversion, put back afterwards."""

    kind: str  # "math" | "code"
    text: str  # the LaTeX, or the code
    display: bool = False
    lang: str = ""

    @property
    def block(self) -> bool:
        return self.kind == "code" or self.display

    def as_block(self) -> str:
        if self.kind == "code":
            fence = "````" if "```" in self.text else "```"
            return f"{fence}{self.lang}\n{self.text}\n{fence}"
        return f"$$\n{self.text}\n$$" if "\n" in self.text else f"$${self.text}$$"

    def as_inline(self) -> str:
        """The piece on one line (in a table cell)."""
        if self.kind == "math":
            return f"$${' '.join(self.text.split())}$$" if self.display else f"${self.text}$"
        code = " ".join(ln.strip() for ln in self.text.splitlines() if ln.strip())
        ticks = "``" if "`" in code else "`"
        return f"{ticks}{code}{ticks}"


def _stash(stash: list[_Piece], piece: _Piece) -> str:
    stash.append(piece)
    return _TOKEN.format(len(stash) - 1)


def _block_holder(soup: BeautifulSoup, token: str) -> Tag:
    """A paragraph holding a block piece's token: markdownify then indents it inside a list item
    and puts ``>`` before it inside a quote, like any other paragraph there."""
    holder = soup.new_tag("p")
    holder.string = token
    return holder


# ---- math ------------------------------------------------------------------------------------

_DISPLAYSTYLE = re.compile(r"^\{\\displaystyle\s*(.*)\}$", re.S)


def _clean_latex(latex: str, display: bool) -> str:
    latex = latex.strip()
    m = _DISPLAYSTYLE.match(latex)  # Wikipedia wraps every formula in {\displaystyle ...}
    if m:
        latex = m.group(1).strip()
    if display:  # a blank line ends a display block in markdown (and is an error in TeX)
        latex = re.sub(r"\n[ \t]*(?:\n[ \t]*)+", "\n", latex)
    return latex


def _latex_of(node: Tag) -> str | None:
    """The LaTeX source of a rendered formula, or ``None`` if it cannot be found."""
    if node.get("data-math"):
        return str(node["data-math"]).strip()
    annotation = node.find("annotation", attrs={"encoding": re.compile(r"tex", re.I)})
    if annotation is not None:
        return annotation.get_text().strip()
    if node.get("data-latex"):
        return str(node["data-latex"]).strip()
    return None


def _math_source(node: Tag) -> str | None:
    """LaTeX for a node holding MathML: its TeX annotation, its ``alttext``, else the MathML read
    as LaTeX."""
    latex = _latex_of(node)
    if latex is not None:
        return latex
    math = node if node.name == "math" else node.find("math")
    if not isinstance(math, Tag):
        return None
    if math.get("alttext"):
        return str(math["alttext"]).strip()
    return mathml_to_latex(math) or None


def _put_math(
    soup: BeautifulSoup, node: Tag, latex: str, display: bool, stash: list[_Piece]
) -> None:
    token = _stash(stash, _Piece("math", _clean_latex(latex, display), display))
    node.replace_with(_block_holder(soup, token) if display else NavigableString(token))


def _extract_math(soup: BeautifulSoup, stash: list[_Piece]) -> None:
    """Replace every rendered formula (and its visual duplicate) by a placeholder token."""
    # MathJax 2: <script type="math/tex; mode=display"> next to its rendered copy
    scripts = soup.find_all("script", attrs={"type": re.compile(r"^math/tex", re.I)})
    if scripts:
        for dup in soup.find_all(class_=re.compile(r"^(MathJax\w*|MJX\w*)$")):
            dup.decompose()
    for script in scripts:
        _put_math(soup, script, script.get_text(), "display" in str(script.get("type", "")), stash)
    # Gemini: data-math on the wrapper; KaTeX: .katex(-display); outer-most first so that a
    # wrapper never leaves its inner formula behind
    selector = re.compile(r"katex-display|math-block|math-display", re.I)
    for node in list(soup.find_all(class_=selector)):
        if node.parent is None:
            continue
        latex = _latex_of(node) or _latex_of_inner(node)
        if latex is not None:
            _put_math(soup, node, latex, True, stash)
    for node in list(soup.find_all(class_=re.compile(r"^(katex|math-inline|math)$", re.I))):
        if node.parent is None:
            continue
        latex = _latex_of(node)
        if latex is not None:
            _put_math(soup, node, latex, False, stash)
        elif "katex" in (node.get("class") or []):
            html_part = node.find(class_="katex-html")
            node.replace_with(NavigableString((html_part or node).get_text()))
    # Wikipedia: MathML (with a TeX annotation) + a fallback image, in one wrapper
    for node in list(soup.find_all(class_="mwe-math-element")):
        if node.parent is None:
            continue
        latex = _math_source(node)
        if latex is not None:
            display = node.find(class_=re.compile(r"mwe-math-(mathml|fallback-image)-display"))
            _put_math(soup, node, latex, display is not None, stash)
    # MathJax 3: the TeX is gone; the assistive MathML is the only exact copy
    for node in list(soup.find_all("mjx-container")):
        if node.parent is None:
            continue
        latex = _math_source(node)
        if latex is not None:
            _put_math(soup, node, latex, node.get("display") == "true", stash)
    # plain MathML anywhere else
    for node in list(soup.find_all("math")):
        if node.parent is None:
            continue
        latex = _math_source(node)
        if latex is not None:
            _put_math(soup, node, latex, node.get("display") == "block", stash)


def _latex_of_inner(node: Tag) -> str | None:
    inner = node.find(class_="katex")
    return _latex_of(inner) if inner is not None else None


# MathML -> LaTeX for the common elements (MathJax 3 and MathML pages keep no TeX source)
_MO = {
    "∑": r"\sum", "∏": r"\prod", "∫": r"\int", "∮": r"\oint", "±": r"\pm", "∓": r"\mp",
    "×": r"\times", "÷": r"\div", "⋅": r"\cdot", "·": r"\cdot", "−": "-", "≤": r"\le",
    "≥": r"\ge", "≠": r"\neq", "≈": r"\approx", "≡": r"\equiv", "∝": r"\propto", "→": r"\to",
    "←": r"\leftarrow", "⇒": r"\Rightarrow", "⇔": r"\Leftrightarrow", "↔": r"\leftrightarrow",
    "∞": r"\infty", "∂": r"\partial", "∇": r"\nabla", "∈": r"\in", "∉": r"\notin",
    "⊂": r"\subset", "⊆": r"\subseteq", "∪": r"\cup", "∩": r"\cap", "∀": r"\forall",
    "∃": r"\exists", "¬": r"\neg", "∧": r"\land", "∨": r"\lor", "…": r"\ldots", "⋯": r"\cdots",
    "{": r"\{", "}": r"\}", "⁡": "", "⁢": "", "⁣": "", "⁤": "",
}  # fmt: skip
_ACCENT = {"^": r"\hat", "ˆ": r"\hat", "¯": r"\overline", "‾": r"\overline", "→": r"\vec",
           "~": r"\tilde", "˜": r"\tilde", "˙": r"\dot", "¨": r"\ddot"}  # fmt: skip
_BIG = {r"\sum", r"\prod", r"\int", r"\oint", r"\lim", r"\max", r"\min"}
_FUNCS = {"sin", "cos", "tan", "log", "ln", "exp", "lim", "max", "min", "det", "sup", "inf"}


def mathml_to_latex(el: Tag | NavigableString) -> str:
    """LaTeX for a MathML element (the common presentation elements; others give their text)."""
    if isinstance(el, NavigableString):
        return "" if isinstance(el, Comment) else str(el).strip()
    name = (el.name or "").split(":")[-1]
    kids = [c for c in el.children if isinstance(c, Tag)]
    parts = [mathml_to_latex(k) for k in kids]

    def arg(i: int) -> str:
        return parts[i] if i < len(parts) else ""

    text = el.get_text().strip()
    if name in ("annotation", "annotation-xml"):
        return ""
    if name == "semantics":
        return arg(0)
    if name == "mi":
        if text in _FUNCS:
            return "\\" + text
        return text if len(text) <= 1 else f"\\mathrm{{{text}}}"
    if name == "mn":
        return text
    if name == "mo":
        return _MO.get(text, text)
    if name == "mtext":
        return f"\\text{{{text}}}" if text else ""
    if name == "mspace":
        return r"\,"
    if name == "msup":
        return f"{{{arg(0)}}}^{{{arg(1)}}}"
    if name == "msub":
        return f"{{{arg(0)}}}_{{{arg(1)}}}"
    if name == "msubsup":
        return f"{{{arg(0)}}}_{{{arg(1)}}}^{{{arg(2)}}}"
    if name == "mfrac":
        return f"\\frac{{{arg(0)}}}{{{arg(1)}}}"
    if name == "msqrt":
        return f"\\sqrt{{{' '.join(parts)}}}"
    if name == "mroot":
        return f"\\sqrt[{arg(1)}]{{{arg(0)}}}"
    if name in ("mover", "munder", "munderover"):
        base = arg(0)
        if name == "mover" and len(kids) > 1 and kids[1].get_text().strip() in _ACCENT:
            return f"{_ACCENT[kids[1].get_text().strip()]}{{{base}}}"
        if base in _BIG:
            under = f"_{{{arg(1)}}}" if name != "mover" else ""
            over = f"^{{{arg(2 if name == 'munderover' else 1)}}}" if name != "munder" else ""
            return base + under + over
        if name == "mover":
            return f"\\overset{{{arg(1)}}}{{{base}}}"
        if name == "munder":
            return f"\\underset{{{arg(1)}}}{{{base}}}"
        return f"\\overset{{{arg(2)}}}{{\\underset{{{arg(1)}}}{{{base}}}}}"
    if name == "mfenced":
        opener, closer = str(el.get("open", "(")), str(el.get("close", ")"))
        sep = str(el.get("separators", ",")).strip()[:1]
        left, right = _MO.get(opener, opener) or ".", _MO.get(closer, closer) or "."
        return f"\\left{left} {(sep + ' ').join(parts)} \\right{right}"
    if name == "mtable":
        return "\\begin{matrix} " + r" \\ ".join(parts) + " \\end{matrix}"
    if name == "mtr":
        return " & ".join(parts)
    return " ".join(p for p in parts if p) if kids else text


# ---- code ------------------------------------------------------------------------------------


def _language_of(pre: Tag, code: Tag | None) -> tuple[str, Tag | None]:
    """The language of a code block and, if it came from a header label, that label element."""
    from_class = ""
    for tag in (code, pre, *pre.parents):
        if not isinstance(tag, Tag):
            continue
        for cls in tag.get("class") or []:
            m = re.match(r"(?:language|lang)-([\w+#.-]+)$", cls)
            if m and not from_class:
                from_class = m.group(1).lower()
        if tag is not code and tag is not pre:
            break
    # a short label in the block's header ("python", "Python", "TypeScript")
    candidates = list(pre.find_all(["span", "div", "p"]))[:6]
    ancestor: Tag | None = pre.parent
    for _ in range(3):  # the header may sit a few levels up (Gemini)
        if ancestor is None:
            break
        candidates += [
            el
            for el in ancestor.find_all(["span", "div"])
            if pre not in el.parents and el is not pre and pre not in el.descendants
        ][:12]
        ancestor = ancestor.parent
    for el in candidates:
        if el.find(True) is not None or (code is not None and el in code.descendants):
            continue  # only leaf labels, never the code itself
        text = el.get_text(strip=True)
        if (
            text
            and len(text) <= 20
            and re.fullmatch(r"[A-Za-z][\w+#.-]*", text)
            and text.lower() not in _JUNK_TEXT
            and (not from_class or text.lower() == from_class)
        ):
            return text.lower(), el
    return from_class, None


def _extract_code(soup: BeautifulSoup, stash: list[_Piece]) -> None:
    for pre in list(soup.find_all("pre")):
        if pre.parent is None:
            continue
        code = pre.find("code")
        source = code if code is not None else pre
        for br in source.find_all("br"):
            br.replace_with(NavigableString("\n"))
        if code is None:  # no <code>: the text of the <pre>, minus buttons and header labels
            for junk in source.find_all(["button", "svg"]):
                junk.decompose()
        text = source.get_text().strip("\n")
        label_lang, label = _language_of(pre, code)
        if label is not None and label.parent is not None and pre not in label.parents:
            label.decompose()  # the header label sits next to the block, not inside it
        if not text.strip():
            pre.decompose()
            continue
        token = _stash(stash, _Piece("code", text, lang=label_lang))
        pre.replace_with(_block_holder(soup, token))


# ---- page structure --------------------------------------------------------------------------


def _drop_interface(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(["meta", "style", "link", "button", "svg", "noscript", "template"]):
        tag.decompose()
    for tag in soup.find_all("script"):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag in list(soup.find_all(True)):
        if tag.parent is None:
            continue
        classes = " ".join(tag.get("class") or [])
        testid = str(tag.get("data-testid", ""))
        text = tag.get_text(strip=True)
        holds_content = bool(_TOKEN_RE.search(text))  # a code block / formula already taken out
        if (classes and _JUNK_CLASS.search(classes) and len(text) <= 40 and not holds_content) or (
            "citation" in testid
        ):
            tag.decompose()
    for text in soup.find_all(string=True):
        if text.strip().lower() in _JUNK_TEXT and text.parent is not None:
            parent = text.parent
            if parent.name in {"span", "div", "p"} and len(parent.get_text(strip=True)) <= 12:
                parent.decompose()


_WEIGHT_NORMAL = re.compile(r"font-weight\s*:\s*(normal|[1-4]00)", re.I)
_BOLD = re.compile(r"font-weight\s*:\s*(bold|[6-9]00)", re.I)
_ITALIC = re.compile(r"font-style\s*:\s*italic", re.I)
_STRIKE = re.compile(r"text-decoration[\w-]*\s*:[^;]*line-through", re.I)


def _fix_wrappers(soup: BeautifulSoup) -> None:
    """Word processors (Google Docs, Word) wrap whole documents in inline tags and mark bold /
    italic with styles. An inline tag around blocks (a table in ``<b>``) would turn into ``**``
    around the whole table, so it is unwrapped; a styled span becomes the tag it means."""
    for tag in list(
        soup.find_all(["b", "strong", "i", "em", "u", "span", "font", "a", "del", "s"])
    ):
        if tag.parent is None:
            continue
        style = str(tag.get("style", ""))
        if tag.find(_BLOCK_TAGS) is not None or (
            tag.name in ("b", "strong") and _WEIGHT_NORMAL.search(style)
        ):
            tag.unwrap()
            continue
        if tag.name != "span" or not style or not tag.get_text(strip=True):
            continue
        for pattern, name in ((_STRIKE, "del"), (_ITALIC, "em"), (_BOLD, "strong")):
            if pattern.search(style):
                tag.wrap(soup.new_tag(name))


# ---- markdown --------------------------------------------------------------------------------

_CELL, _CELL_END, _ROW, _ROW_END, _SEP = "\x01", "\x02", "\x03", "\x04", "\x1f"
_ROW_RE = re.compile(f"{_ROW}([hb]){_SEP}(.*?){_ROW_END}", re.S)
_CELL_RE = re.compile(f"{_CELL}(\\d+){_SEP}([^{_SEP}]*?){_SEP}(.*?){_CELL_END}", re.S)


class _Converter(MarkdownConverter):
    def __init__(self, stash: list[_Piece], **options: Any) -> None:
        super().__init__(**options)
        self.stash = stash

    def convert_input(self, el: Tag, text: str, parent_tags: Any = None) -> str:
        """Task list boxes."""
        if el.get("type") == "checkbox":
            return "[x]" if el.has_attr("checked") else "[ ]"
        return ""

    # Tables: cells and rows are marked here and laid out in convert_table, where the whole grid
    # is known (header, column count, alignment).
    def _cell(self, el: Tag, text: str) -> str:
        span = str(el.get("colspan", "1"))
        count = max(1, min(50, int(span))) if span.isdigit() else 1
        style = str(el.get("style", ""))
        m = re.search(r"text-align\s*:\s*(left|center|right)", style, re.I)
        align = str(el.get("align", "")).lower() or (m.group(1).lower() if m else "")
        # one line; formulas and code blocks in their one-line form
        value = _TOKEN_RE.sub(lambda t: self.stash[int(t.group(1))].as_inline(), text)
        value = " ".join(value.split())
        return f"{_CELL}{count}{_SEP}{align}{_SEP}{value}{_CELL_END}"

    def convert_td(self, el: Tag, text: str, parent_tags: Any = None) -> str:
        return self._cell(el, text)

    def convert_th(self, el: Tag, text: str, parent_tags: Any = None) -> str:
        return self._cell(el, text)

    def convert_tr(self, el: Tag, text: str, parent_tags: Any = None) -> str:
        cells = el.find_all(["td", "th"], recursive=False)
        head = bool(cells) and (
            all(c.name == "th" for c in cells)
            or (el.parent is not None and el.parent.name == "thead")
        )
        return f"{_ROW}{'h' if head else 'b'}{_SEP}{text}{_ROW_END}"

    def convert_table(self, el: Tag, text: str, parent_tags: Any = None) -> str:
        rows: list[tuple[bool, list[tuple[str, str]]]] = []
        for kind, body in _ROW_RE.findall(text):
            cells: list[tuple[str, str]] = []
            for count, align, value in _CELL_RE.findall(body):
                cells.append((value, align))
                cells += [("", align)] * (int(count) - 1)
            if cells:
                rows.append((kind == "h", cells))
        if not rows:
            return ""
        width = max(len(cells) for _, cells in rows)
        grid = [[v for v, _ in cells] + [""] * (width - len(cells)) for _, cells in rows]
        first = rows[0][1]
        aligns = [first[i][1] if i < len(first) else "" for i in range(width)]
        # the first row is the header (GFM needs one): a page without <th> has its titles there
        return "\n\n" + _table_md(grid[0], aligns, grid[1:]) + "\n\n"


def _table_md(header: list[str], aligns: list[str], rows: list[list[str]]) -> str:
    def esc(value: str) -> str:
        return value.replace("|", "\\|")

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(esc(c) for c in cells) + " |"

    marks = {"left": ":---", "center": ":---:", "right": "---:"}
    delimiter = "| " + " | ".join(marks.get(a, "---") for a in aligns) + " |"
    return "\n".join([line(header), delimiter, *(line(r) for r in rows)])


_LIST_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _tighten_lists(md: str) -> str:
    """No empty line between list lines (chat pages wrap every item in a paragraph)."""
    lines = md.split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        if not line.strip() and out and _LIST_LINE.match(out[-1]):
            nxt = next((ln for ln in lines[i + 1 :] if ln.strip()), "")
            if _LIST_LINE.match(nxt):
                continue
        out.append(line)
    return "\n".join(out)


_BLOCK_LINE = re.compile(r"([ \t>]*)\x00(\d+)\x00[ \t]*")


def _put_back(md: str, stash: list[_Piece]) -> str:
    """The formulas and code blocks back in place of their tokens. A block alone on its line
    gets that line's indentation / quote marks on each of its lines, so it stays in its list item
    or quote."""
    out: list[str] = []
    for line in md.split("\n"):
        m = _BLOCK_LINE.fullmatch(line)
        if m and stash[int(m.group(2))].block:
            prefix = m.group(1)
            for part in stash[int(m.group(2))].as_block().split("\n"):
                out.append(prefix + part if part else prefix.rstrip())
            continue
        out.append(
            _TOKEN_RE.sub(
                lambda t: (
                    f"\n\n{stash[int(t.group(1))].as_block()}\n\n"
                    if stash[int(t.group(1))].block
                    else stash[int(t.group(1))].as_inline()
                ),
                line,
            )
        )
    return "\n".join(out)


def html_to_md(html: str) -> str:
    """Markdown for the clipboard ``html`` (see the module docstring)."""
    soup = BeautifulSoup(html, "html.parser")
    stash: list[_Piece] = []
    _extract_math(soup, stash)
    _extract_code(soup, stash)  # before the interface goes: the block header names the language
    _drop_interface(soup)
    _fix_wrappers(soup)
    md = _Converter(
        stash,
        heading_style="ATX",
        bullets="-",
        strong_em_symbol="*",
        escape_underscores=False,
        escape_misc=False,
    ).convert_soup(soup)
    md = _tighten_lists(md)
    md = _put_back(md, stash)
    md = re.sub(r"[ \t]+\n", "\n", md)  # trailing spaces (but not a hard break at the end)
    md = re.sub(r"\n{3,}", "\n\n", md).strip("\n")
    return md


# ---- plain text ------------------------------------------------------------------------------

_CODE = re.compile(r"(```.*?```|~~~.*?~~~|``[^`\n]+``|`[^`\n]+`)", re.DOTALL)
# `\[` that is not the end of a `\\` line break (`a \\[4pt] b` in a matrix)
_DISPLAY = re.compile(r"(?<!\\)\\\[(.+?)(?<!\\)\\\]", re.DOTALL)
_INLINE = re.compile(r"(?<!\\)\\\((.+?)(?<!\\)\\\)", re.DOTALL)


def _convert_outside_code(text: str) -> str:
    def display(m: re.Match[str]) -> str:
        body = _clean_latex(m.group(1), display=True)
        return f"$${body}$$" if "\n" not in body else f"$$\n{body}\n$$"

    text = _DISPLAY.sub(display, text)
    return _INLINE.sub(lambda m: f"${m.group(1).strip()}$", text)


def normalize(text: str) -> str:
    """``\\( x \\)`` -> ``$x$`` and ``\\[ x \\]`` -> ``$$x$$`` (display); code is left as it is."""
    parts = _CODE.split(text)
    return "".join(p if i % 2 else _convert_outside_code(p) for i, p in enumerate(parts))


# ---- deciding --------------------------------------------------------------------------------

# blocks that change meaning when text shares their first or last line: a fence or `$$` after
# text is no fence, a heading mark mid-line is text, a table takes the next text line as a row
_EDGE_BLOCKS = {"table_open", "fence", "code_block", "math_block", "heading_open", "hr"}
_SWALLOWS_NEXT = {"table_close", "fence", "math_block"}


def needs_own_lines(md: str) -> bool:
    """Must the pasted ``md`` start and end on lines of its own to render as it should?"""
    top = [t for t in parse(md) if t.level == 0 and t.type != "front_matter"]
    if not top:
        return False
    return top[0].type in _EDGE_BLOCKS or top[-1].type in _SWALLOWS_NEXT


def smart_paste(html: str, text: str) -> str:
    """The markdown to insert for a paste of ``html`` / ``text`` (either may be empty).

    HTML is used when it carries real structure (headings, lists, tables, code, math, emphasis,
    links, images); a plain copy that merely wraps text in ``<div>``/``<span>`` keeps the exact
    plain text instead.
    """
    if html.strip() and _SEMANTIC.search(html):
        converted = html_to_md(html)
        if converted.strip():
            return normalize(converted)
    return normalize(text)
