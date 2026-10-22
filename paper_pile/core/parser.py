"""Markdown parsing for everything that is not the editor: HTML rendering, link/outline
extraction (later tasks), AI chat replies, export.

One configured :class:`markdown_it.MarkdownIt` is the reference for what a note *means*:
CommonMark + GFM tables, strikethrough, task lists, footnotes, YAML front matter and
dollar math. The editor's own Lezer grammar (``tools/editor_src/math.js``) must agree with
the math rules below; ``tests/fixtures/math_cases.json`` is checked against both.

Math rules (the pandoc convention, as implemented by ``mdit_py_plugins.dollarmath``):

* ``$inline$``: no whitespace right after the opening ``$`` or right before the closing one,
  no digit directly before the opening or after the closing ``$`` (so ``$5 and $10`` is text),
  ``\\$`` is a literal dollar, content is not empty. The *first* unescaped closing ``$``
  decides: if it is invalid the opening ``$`` is plain text (no scanning further).
* ``$$inline$$`` inside a paragraph is allowed and has no whitespace rules.
* ``$$`` block: a line starting with ``$$`` (indent < 4) that closes on the same line
  (``$$x$$``) or on a later line ending in ``$$``. An unclosed block, or one with a blank
  line before its closing ``$$``, is plain text. A block may directly follow a paragraph line.

Raw HTML in notes is escaped, not passed through: rendered output is used in places that
must stay safe (chat replies, exports). The one exception is a page break line
(:mod:`paper_pile.core.pagebreak`), which becomes ``<div class="pp-page-break">``. Single
newlines render as line breaks, matching what the editor shows.
"""

import re
from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

import yaml
from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.renderer import RendererProtocol
from markdown_it.rules_block import StateBlock
from markdown_it.rules_core import StateCore
from markdown_it.rules_inline import StateInline
from markdown_it.rules_inline.image import image as _image_rule
from markdown_it.rules_inline.link import link as _link_rule
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.dollarmath.index import math_block_dollar
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from paper_pile.core import pagebreak
from paper_pile.core.links import WikiTarget, parse_wikilink
from paper_pile.core.tags import property_tags, starts_tag, tag_body, unique

_PARAGRAPH_LIKE = ["paragraph", "reference", "blockquote", "list"]


def make_parser(*, breaks: bool = True) -> MarkdownIt:
    """A fresh configured parser (cheap; the module-level one below is shared)."""
    md = (
        MarkdownIt("commonmark", {"html": False, "breaks": breaks})
        .enable(["table", "strikethrough"])
        .use(footnote_plugin)
        .use(tasklists_plugin, enabled=True)
        .use(
            dollarmath_plugin,
            allow_labels=False,
            allow_space=False,
            allow_digits=False,
            allow_blank_lines=False,
            double_inline=True,
        )
    )
    md.block.ruler.before("table", "front_matter", _front_matter_rule)
    md.block.ruler.before("html_block", "page_break", _page_break_rule)
    md.core.ruler.push("page_break_effect", _page_break_effect)
    md.inline.ruler.before("link", "wikilink", _wikilink_rule)
    md.inline.ruler.before("wikilink", "hashtag", _hashtag_rule)
    md.inline.ruler.at("link", _located_link_rule)
    md.inline.ruler.at("image", _located_image_rule)
    md.add_render_rule("wikilink", _render_wikilink)
    md.add_render_rule("hashtag", _render_hashtag)
    md.add_render_rule("page_break", _render_page_break)
    # let a `$$` block start right after a paragraph line (the plugin's own registration cannot)
    md.block.ruler.at("math_block", _interrupting_math_block(), {"alt": _PARAGRAPH_LIKE})
    return md


def _wikilink_rule(state: StateInline, silent: bool) -> bool:
    """``[[note]]``, ``[[note|alias]]``, ``[[note#heading]]``, ``[[#heading]]``.

    The text between ``[[`` and the first ``]]`` must sit on one line, contain no ``[`` or ``]``
    and name something (see :func:`~paper_pile.core.links.parse_wikilink`). Code spans and
    fenced code are consumed by earlier rules, so a wikilink inside them is never seen here.
    """
    src, pos = state.src, state.pos
    if not src.startswith("[[", pos):
        return False
    end = src.find("]]", pos + 2, state.posMax)
    if end == -1:
        return False
    inner = src[pos + 2 : end]
    if "\n" in inner or "[" in inner or "]" in inner:
        return False
    target = parse_wikilink(inner)
    if target is None:
        return False
    if not silent:
        token = state.push("wikilink", "", 0)
        token.content = inner
        token.meta = {
            "note": target.note,
            "heading": target.heading,
            "alias": target.alias,
            "pos": pos,
        }
    state.pos = end + 2
    return True


def _hashtag_rule(state: StateInline, silent: bool) -> bool:
    """``#tag``: see :mod:`paper_pile.core.tags` (code spans are consumed earlier)."""
    src, pos = state.src, state.pos
    if pos >= state.posMax or not starts_tag(src, pos):
        return False
    body = tag_body(src[: state.posMax], pos + 1)
    if not body:
        return False
    if not silent:
        token = state.push("hashtag", "", 0)
        token.content = body
        token.meta = {"pos": pos}
    state.pos = pos + 1 + len(body)
    return True


def _render_hashtag(
    self: RendererProtocol,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    tag = escapeHtml(tokens[idx].content)
    return f'<a class="tag" data-tag="{tag}">#{tag}</a>'


def _located_link_rule(state: StateInline, silent: bool) -> bool:
    """markdown-it's own ``link`` rule, plus where the link sits in the inline text and its
    source text, so :func:`link_spans` can find it again in the file."""
    start, mark = state.pos, len(state.tokens)
    matched = _link_rule(state, silent)
    if matched and not silent:
        for tok in state.tokens[mark:]:
            if tok.type == "link_open":
                tok.meta = {"pos": start, "source": state.src[start : state.pos]}
                break
    return matched


def _located_image_rule(state: StateInline, silent: bool) -> bool:
    """markdown-it's ``image`` rule, remembering where the image sits in the inline text."""
    start, mark = state.pos, len(state.tokens)
    matched = _image_rule(state, silent)
    if matched and not silent:
        for tok in state.tokens[mark:]:
            if tok.type == "image":
                tok.meta = {"pos": start, "source": state.src[start : state.pos]}
                break
    return matched


def _render_wikilink(
    self: RendererProtocol,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    meta: MutableMapping[str, str] = tokens[idx].meta
    target = parse_wikilink(tokens[idx].content)
    text = target.text if target else tokens[idx].content
    note, heading = escapeHtml(meta["note"]), escapeHtml(meta["heading"])
    return f'<a class="wikilink" data-note="{note}" data-heading="{heading}">{escapeHtml(text)}</a>'


def _front_matter_rule(state: StateBlock, start: int, end: int, silent: bool) -> bool:
    """YAML front matter: only at the very top, opened by a line that is exactly ``---`` and
    closed by the next line that is exactly ``---``. Anything else is not front matter.

    (The plugin's own rule also accepts ``----`` openers, text after the dashes and a ``...``
    closer, which the editor grammar would have to copy; a plain rule is easier to keep in sync.)
    """
    if start != 0:
        return False
    lines = state.src.split("\n")
    if lines[0].rstrip() != "---":
        return False
    close = next((i for i in range(1, min(len(lines), end)) if lines[i].rstrip() == "---"), None)
    if close is None:
        return False  # unclosed: ordinary markdown
    if silent:
        return True
    token = state.push("front_matter", "", 0)
    token.hidden = True
    token.markup = "---"
    token.block = True
    token.content = state.getLines(1, close, 0, False)
    state.line = close + 1
    token.map = [0, state.line]
    return True


def _page_break_rule(state: StateBlock, start: int, end: int, silent: bool) -> bool:
    """A page break line (:mod:`paper_pile.core.pagebreak`): top level only, with an empty line
    (or the start/end of the file) above and below. It never interrupts a paragraph."""
    # not `parentType`: markdown-it's lheading rule leaves it at "paragraph" when it fails
    if state.level != 0:
        return False
    if not pagebreak.is_break_line(state.src[state.bMarks[start] : state.eMarks[start]]):
        return False
    if start > 0 and not state.isEmpty(start - 1):
        return False
    if start + 1 < end and not state.isEmpty(start + 1):
        return False
    if silent:
        return True
    token = state.push("page_break", "div", 0)
    token.block = True
    token.map = [start, start + 1]
    token.meta = {"effective": False}
    state.line = start + 1
    return True


def _page_break_effect(state: StateCore) -> None:
    """Mark the page breaks that start a new page (``meta["effective"]``)."""
    blocks = [t for t in state.tokens if t.level == 0 and t.nesting >= 0 and not t.hidden]
    flags = pagebreak.effective([t.type == "page_break" for t in blocks])
    for tok, flag in zip(blocks, flags, strict=True):
        if tok.type == "page_break":
            tok.meta["effective"] = flag


def _render_page_break(
    self: RendererProtocol,
    tokens: Sequence[Token],
    idx: int,
    options: OptionsDict,
    env: EnvType,
) -> str:
    return '<div class="pp-page-break"></div>\n' if tokens[idx].meta["effective"] else ""


def _interrupting_math_block() -> Callable[[StateBlock, int, int, bool], bool]:
    """The plugin's block rule, made safe to use as a paragraph terminator.

    The plugin rule ignores ``silent`` and always emits a token and moves ``state.line``;
    called from a paragraph's terminator check that would duplicate blocks. In silent mode we
    run it, undo its side effects and only report whether a block starts here.
    """
    rule = math_block_dollar(allow_labels=False, allow_blank_lines=False)

    def wrapped(state: StateBlock, start: int, end: int, silent: bool) -> bool:
        if not silent:
            return rule(state, start, end, False)
        line, ntokens = state.line, len(state.tokens)
        found = rule(state, start, end, False)
        del state.tokens[ntokens:]
        state.line = line
        return found

    return wrapped


_PARSER = make_parser()


def render_html(text: str) -> str:
    """Render a note's markdown to HTML (front matter is dropped, math is left as spans)."""
    return str(_PARSER.render(text))


@dataclass(frozen=True, slots=True)
class FrontMatter:
    raw: str  # the YAML text between the --- lines
    data: dict[str, Any]  # parsed mapping; {} if the YAML is not a mapping
    error: str | None = None  # why parsing failed, if it did


def parse(text: str) -> list[Token]:
    """The token stream of ``text``; pass it to the functions below that take ``tokens`` when
    several of them read the same note (each parse costs about a millisecond)."""
    return list(_PARSER.parse(text))


def front_matter(text: str, tokens: list[Token] | None = None) -> FrontMatter | None:
    """The note's YAML front matter, or ``None`` if it has none."""
    tokens = parse(text) if tokens is None else tokens
    if not tokens or tokens[0].type != "front_matter":
        return None
    raw = tokens[0].content
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return FrontMatter(raw, {}, str(exc).splitlines()[0])
    if loaded is None:
        return FrontMatter(raw, {})
    if not isinstance(loaded, dict):
        return FrontMatter(raw, {}, "front matter is not a key: value mapping")
    return FrontMatter(raw, loaded)


def body_start(text: str) -> int:
    """Where the note's body begins: just after its front matter (0 when it has none)."""
    tokens = _PARSER.parse(text)
    if not tokens or tokens[0].type != "front_matter" or not tokens[0].map:
        return 0
    lines = text.split("\n")
    end_line = tokens[0].map[1]
    return min(len(text), sum(len(line) + 1 for line in lines[:end_line]))


def inline_tags(text: str, tokens: list[Token] | None = None) -> list[str]:
    """Every inline ``#tag`` in ``text`` as written (without ``#``), in order."""
    found: list[str] = []
    for tok in parse(text) if tokens is None else tokens:
        if tok.type == "inline" and tok.children:
            found.extend(c.content for c in tok.children if c.type == "hashtag")
    return found


def note_tags(text: str, tokens: list[Token] | None = None) -> list[str]:
    """A note's tags: its ``tags`` property first, then inline tags; one per tag."""
    tokens = parse(text) if tokens is None else tokens
    fm = front_matter(text, tokens)
    return unique([*(property_tags(fm.data) if fm else []), *inline_tags(text, tokens)])


@dataclass(frozen=True, slots=True)
class PageBreak:
    line: int  # 1-based
    effective: bool  # starts a new page (see :func:`paper_pile.core.pagebreak.effective`)


def page_breaks(text: str, tokens: list[Token] | None = None) -> list[PageBreak]:
    """The note's page break lines, in order."""
    return [
        PageBreak(t.map[0] + 1, bool(t.meta["effective"]))
        for t in (parse(text) if tokens is None else tokens)
        if t.type == "page_break" and t.map
    ]


def math_spans(text: str) -> tuple[list[str], list[str]]:
    """``(inline, block)`` math contents found in ``text``, in order. Used by the sync tests."""
    inline: list[str] = []
    block: list[str] = []

    def walk(tokens: list[Any]) -> None:
        for tok in tokens:
            if tok.type in ("math_inline", "math_inline_double"):
                inline.append(tok.content)
            elif tok.type == "math_block":
                block.append(tok.content.strip())
            if tok.children:
                walk(tok.children)

    walk(_PARSER.parse(text))
    return inline, block


def wikilinks(text: str) -> list[WikiTarget]:
    """Every ``[[wikilink]]`` in ``text``, in order (code spans and code blocks excluded)."""
    found: list[WikiTarget] = []

    def walk(tokens: list[Any]) -> None:
        for tok in tokens:
            if tok.type == "wikilink":
                meta = tok.meta
                found.append(WikiTarget(meta["note"], meta["heading"], meta["alias"]))
            if tok.children:
                walk(tok.children)

    walk(_PARSER.parse(text))
    return found


@dataclass(frozen=True, slots=True)
class LinkRef:
    kind: str  # "wiki" | "md" (a relative markdown link to another note)
    raw: str  # wiki: the text inside [[ ]]; md: the href
    line: int  # 1-based line of the paragraph/heading holding it


def note_links(text: str, tokens: list[Token] | None = None) -> list[LinkRef]:
    """Links that point at other notes: ``[[wikilinks]]`` and relative markdown links."""
    found: list[LinkRef] = []

    for tok in parse(text) if tokens is None else tokens:
        if tok.type != "inline" or not tok.children:
            continue
        line = (tok.map[0] + 1) if tok.map else 1
        for child in tok.children:
            if child.type in {"softbreak", "hardbreak"}:
                line += 1
            elif child.type == "wikilink":
                found.append(LinkRef("wiki", child.content, line))
            elif child.type == "link_open":
                href = str(child.attrGet("href") or "")
                if href and not href.startswith(("#", "/", "//")) and ":" not in href.split("/")[0]:
                    found.append(LinkRef("md", href, line))
    return found


@dataclass(frozen=True, slots=True)
class Heading:
    level: int
    text: str
    line: int  # 1-based


def headings(text: str) -> list[Heading]:
    """The note's headings, in order (``#`` and underlined; not ``#`` inside code)."""
    found: list[Heading] = []
    tokens = _PARSER.parse(text)
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open" and tok.map and i + 1 < len(tokens):
            inline = tokens[i + 1]
            plain = "".join(
                " " if c.type == "softbreak" else c.content
                for c in (inline.children or [])
                if c.type in {"text", "code_inline", "softbreak"}
            )
            found.append(Heading(int(tok.tag[1:]), plain.strip(), tok.map[0] + 1))
    return found


def section_at(heads: list[Heading], line: int) -> int | None:
    """Index of the heading whose section holds 1-based ``line`` (the last one at or above it);
    ``None`` above the first heading."""
    found = None
    for i, head in enumerate(heads):
        if head.line > line:
            break
        found = i
    return found


def find_heading(text: str, wanted: str) -> Heading | None:
    """The first heading whose text equals ``wanted`` (case-insensitive, whitespace-collapsed)."""

    def norm(s: str) -> str:
        return " ".join(s.split()).casefold()

    target = norm(wanted)
    return next((h for h in headings(text) if norm(h.text) == target), None)


@dataclass(frozen=True, slots=True)
class LinkSpan:
    """A note link with enough information to find it in the raw file (see ``core/rewrite.py``)."""

    kind: str  # "wiki" | "md"
    raw: str  # wiki: the text inside [[ ]]; md: the (normalised) href
    line: int  # 1-based line in the file
    source: str  # the link exactly as written, e.g. ``[[a|b]]`` or ``[t](x.md "title")``
    line_offset: int  # where ``source`` starts inside its (container-stripped) line
    line_text: str  # that line, container prefixes (``> ``, list indent) removed


def link_spans(text: str) -> list[LinkSpan]:
    """Like :func:`note_links`, but with each link's source text and position."""
    found: list[LinkSpan] = []
    for tok in _PARSER.parse(text):
        if tok.type != "inline" or not tok.children:
            continue
        first = (tok.map[0] + 1) if tok.map else 1
        content = tok.content
        for child in tok.children:
            meta = child.meta or {}
            if child.type == "wikilink":
                kind, raw, source = "wiki", child.content, f"[[{child.content}]]"
            elif child.type == "link_open" and "source" in meta:
                href = str(child.attrGet("href") or "")
                if not href or href.startswith(("#", "/", "//")) or ":" in href.split("/")[0]:
                    continue
                kind, raw, source = "md", href, str(meta["source"])
            else:
                continue
            pos = int(meta["pos"])
            line_start = content.rfind("\n", 0, pos) + 1
            line_end = content.find("\n", pos)
            found.append(
                LinkSpan(
                    kind,
                    raw,
                    first + content.count("\n", 0, pos),
                    source,
                    pos - line_start,
                    content[line_start : line_end if line_end >= 0 else len(content)],
                )
            )
    return found


def image_spans(text: str) -> list[LinkSpan]:
    """Every ``![alt](src)`` image in ``text`` (``raw`` is its normalised ``src``), in order."""
    found: list[LinkSpan] = []
    for tok in _PARSER.parse(text):
        if tok.type != "inline" or not tok.children:
            continue
        first = (tok.map[0] + 1) if tok.map else 1
        content = tok.content
        for child in tok.children:
            meta = child.meta or {}
            if child.type != "image" or "source" not in meta:
                continue
            pos = int(meta["pos"])
            line_start = content.rfind("\n", 0, pos) + 1
            line_end = content.find("\n", pos)
            found.append(
                LinkSpan(
                    "image",
                    str(child.attrGet("src") or ""),
                    first + content.count("\n", 0, pos),
                    str(meta["source"]),
                    pos - line_start,
                    content[line_start : line_end if line_end >= 0 else len(content)],
                )
            )
    return found


@dataclass(frozen=True, slots=True)
class PlainLine:
    text: str
    hit: tuple[int, int] | None  # where the wanted link sits in ``text``


_PLAIN_TYPES = {"text", "code_inline", "math_inline", "math_inline_double"}


def plain_line(markdown: str, kind: str = "", raw: str = "") -> PlainLine:
    """One line of markdown as plain text (no ``**``, brackets or URLs), for lists and snippets.

    A wikilink shows its alias or note name, a link its text, an image its alt text. When
    ``kind``/``raw`` name a link (as stored by :func:`note_links`), its place in the result is
    returned as ``hit``.
    """
    parts: list[str] = []
    length = 0
    hit: tuple[int, int] | None = None
    open_at: int | None = None
    wanted = False

    def add(piece: str) -> None:
        nonlocal length
        parts.append(piece)
        length += len(piece)

    for tok in _PARSER.parseInline(markdown):
        for child in tok.children or []:
            if child.type == "wikilink":
                target = parse_wikilink(child.content)
                start = length
                add(target.text if target else child.content)
                if kind == "wiki" and child.content == raw and hit is None:
                    hit = (start, length)
            elif child.type == "link_open":
                open_at = length
                wanted = kind == "md" and str(child.attrGet("href") or "") == raw
            elif child.type == "link_close":
                if wanted and hit is None and open_at is not None:
                    hit = (open_at, length)
                open_at, wanted = None, False
            elif child.type == "image":
                add(re.sub(r"\s*\|\s*\d+\s*$", "", child.content))  # `alt|300`: size, not text
            elif child.type in _PLAIN_TYPES:
                add(child.content)
            elif child.type in {"softbreak", "hardbreak"}:
                add(" ")
    return PlainLine("".join(parts), hit)
