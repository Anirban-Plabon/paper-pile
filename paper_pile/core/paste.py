"""Smart Paste: turn what the clipboard holds into clean markdown (PLAN §4.10).

* ``html_to_md``: HTML from a web page or an AI chat (ChatGPT, Claude, Gemini, DeepSeek, ...) ->
  markdown. Rendered math (KaTeX / MathJax) goes back to ``$..$`` / ``$$..$$``, code blocks become
  fenced blocks with their language, tables and nested lists stay tables and lists, and the chat
  page's own interface (Copy buttons, language labels, citation chips) is dropped.
* ``normalize``: plain text with ``\\( .. \\)`` / ``\\[ .. \\]`` math delimiters becomes
  ``$..$`` / ``$$..$$``, never touching code.
* ``smart_paste``: picks between the two.
"""

import re
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag
from markdownify import MarkdownConverter

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


# ---- HTML -> markdown ------------------------------------------------------------------------


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


def _extract_math(soup: BeautifulSoup, stash: list[str]) -> None:
    """Replace every rendered formula (and its visual duplicate) by a placeholder token."""

    def put(latex: str, display: bool) -> str:
        latex = latex.strip()
        body = (
            f"\n\n$$\n{latex}\n$$\n\n"
            if display and "\n" in latex
            else (f"\n\n$${latex}$$\n\n" if display else f"${latex}$")
        )
        stash.append(body)
        return _TOKEN.format(len(stash) - 1)

    # MathJax scripts: <script type="math/tex; mode=display">
    for script in soup.find_all("script", attrs={"type": re.compile(r"^math/tex", re.I)}):
        display = "display" in str(script.get("type", ""))
        script.replace_with(NavigableString(put(script.get_text(), display)))
    # Gemini: data-math on the wrapper; KaTeX: .katex(-display); outer-most first so that a
    # wrapper never leaves its inner formula behind
    selector = re.compile(r"katex-display|math-block|math-display", re.I)
    for node in list(soup.find_all(class_=selector)):
        if node.parent is None:
            continue
        latex = _latex_of(node) or _latex_of_inner(node)
        if latex is not None:
            node.replace_with(NavigableString(put(latex, True)))
    for node in list(soup.find_all(class_=re.compile(r"^(katex|math-inline|math)$", re.I))):
        if node.parent is None:
            continue
        latex = _latex_of(node)
        if latex is not None:
            node.replace_with(NavigableString(put(latex, False)))
        elif "katex" in (node.get("class") or []):
            html_part = node.find(class_="katex-html")
            node.replace_with(NavigableString((html_part or node).get_text()))


def _latex_of_inner(node: Tag) -> str | None:
    inner = node.find(class_="katex")
    return _latex_of(inner) if inner is not None else None


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


def _extract_code(soup: BeautifulSoup, stash: list[str]) -> None:
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
        fence = "````" if "```" in text else "```"
        stash.append(f"\n\n{fence}{label_lang}\n{text}\n{fence}\n\n")
        pre.replace_with(NavigableString(_TOKEN.format(len(stash) - 1)))


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


class _Converter(MarkdownConverter):
    def convert_input(self, el: Tag, text: str, parent_tags: Any = None) -> str:
        """Task list boxes."""
        if el.get("type") == "checkbox":
            return "[x]" if el.has_attr("checked") else "[ ]"
        return ""


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


def html_to_md(html: str) -> str:
    """Markdown for the clipboard ``html`` (see the module docstring)."""
    soup = BeautifulSoup(html, "html.parser")
    stash: list[str] = []
    _extract_math(soup, stash)
    _extract_code(soup, stash)  # first: the block header still names the language
    _drop_interface(soup)
    md = _Converter(
        heading_style="ATX",
        bullets="-",
        strong_em_symbol="*",
        escape_underscores=False,
        escape_misc=False,
    ).convert_soup(soup)
    md = _tighten_lists(md)
    md = _TOKEN_RE.sub(lambda m: stash[int(m.group(1))], md)
    md = re.sub(
        r"[ \t]+\n", "\n", md
    )  # trailing spaces (but not a two-space hard break at the end)
    md = re.sub(r"\n{3,}", "\n\n", md).strip("\n")
    return md


# ---- plain text ------------------------------------------------------------------------------

_CODE = re.compile(r"(```.*?```|~~~.*?~~~|``[^`\n]+``|`[^`\n]+`)", re.DOTALL)
_DISPLAY = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
_INLINE = re.compile(r"\\\((.+?)\\\)", re.DOTALL)


def _convert_outside_code(text: str) -> str:
    def display(m: re.Match[str]) -> str:
        body = m.group(1).strip()
        return f"$${body}$$" if "\n" not in body else f"$$\n{body}\n$$"

    text = _DISPLAY.sub(display, text)
    return _INLINE.sub(lambda m: f"${m.group(1).strip()}$", text)


def normalize(text: str) -> str:
    """``\\( x \\)`` -> ``$x$`` and ``\\[ x \\]`` -> ``$$x$$`` (display); code is left as it is."""
    parts = _CODE.split(text)
    return "".join(p if i % 2 else _convert_outside_code(p) for i, p in enumerate(parts))


# ---- deciding --------------------------------------------------------------------------------


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
