"""The formatting menu's items (PLAN §4.38): what each does to the note's text.

Pure: ``(text, start, end, kind, arg)`` -> a :class:`~paper_pile.core.command_actions.TextEdit`
whose new selection covers the same words, so running the item again undoes it (every item is a
toggle). Offsets are code points; the GUI converts from / to the browser's UTF-16 offsets.

* Inline marks (bold, italic, strike, code, highlight, underline, colour) go on each selected line
  separately, inside its block prefix (``- ``, ``> ``, ``# ``) and around its words only (markdown
  delimiters must touch the text). They come off when every selected part already has them.
* Line items (quote, lists, headings) set / remove the prefix of every selected line.
* A link wraps the words; a comment goes right after them as ``%%comment%%`` (hidden by the editor,
  never exported).
"""

import re
from dataclasses import dataclass
from typing import Literal

from paper_pile.core.command_actions import TextChange, TextEdit

InlineKind = Literal["bold", "italic", "strike", "code", "highlight", "underline"]
LineKind = Literal["quote", "bullet", "numbered", "todo", "h1", "h2", "h3"]

INLINE: dict[str, tuple[str, str]] = {
    "bold": ("**", "**"),
    "italic": ("*", "*"),
    "strike": ("~~", "~~"),
    "code": ("`", "`"),
    "highlight": ("==", "=="),
    "underline": ("<u>", "</u>"),
}

# Text colours (the editor draws each with a dark-theme variant; any other code is shown as is)
COLORS: dict[str, str] = {
    "gray": "#787774",
    "red": "#e03e3e",
    "orange": "#d9730d",
    "yellow": "#cb912f",
    "green": "#448361",
    "blue": "#337ea9",
    "purple": "#9065b0",
    "pink": "#c14c8a",
}

_NAME_OF: dict[str, str] = {code: name for name, code in COLORS.items()}
# exports and print: a palette name in a span shows paper-pile's shade, not the browser's
COLOR_CSS = "".join(
    f'span[style="color:{name}"] {{ color: {code} !important; }}\n' for name, code in COLORS.items()
)

LINE_KINDS = ("quote", "bullet", "numbered", "todo", "h1", "h2", "h3")
_SPAN_OPEN = re.compile(r'<span style="color:\s*(#[0-9a-fA-F]{3,8}|[a-z]+)\s*;?">$')
_SPAN_CLOSE = "</span>"
# a line's block prefix: quote marks, then indentation and one list / heading marker
_PREFIX = re.compile(
    r"((?:[ \t]*>[ \t]?)*)([ \t]*)((?:#{1,6}|[-*+]|\d{1,9}[.)])[ \t]+(?:\[[ xX]\][ \t]+)?)?"
)
_HEADING = re.compile(r"#{1,6}[ \t]+")
_TASK = re.compile(r"[-*+][ \t]+\[[ xX]\][ \t]+")
_BULLET = re.compile(r"[-*+][ \t]+")
_NUMBER = re.compile(r"\d{1,9}[.)][ \t]+")
COMMENT = re.compile(r"%%([^\n%]*(?:%(?!%)[^\n%]*)*)%%")


@dataclass(frozen=True, slots=True)
class Part:
    """The selected words of one line (code points into the text)."""

    start: int
    end: int


def _parts(text: str, start: int, end: int) -> list[Part]:
    """The selection split per line, each part trimmed of spaces and of the line's block prefix."""
    parts: list[Part] = []
    pos = text.rfind("\n", 0, start) + 1
    while pos <= end:
        line_end = text.find("\n", pos)
        if line_end < 0:
            line_end = len(text)
        body = pos + len(_PREFIX.match(text, pos, line_end).group(0))  # type: ignore[union-attr]
        a, b = max(start, body), min(end, line_end)
        while a < b and text[a] in " \t":
            a += 1
        while b > a and text[b - 1] in " \t":
            b -= 1
        if a < b:
            parts.append(Part(a, b))
        if line_end >= end:
            break
        pos = line_end + 1
    return parts


def _stars(text: str, a: int, b: int) -> tuple[int, int]:
    """How many ``*`` touch the part on its left and on its right."""
    left = 0
    while a - left - 1 >= 0 and text[a - left - 1] == "*":
        left += 1
    right = 0
    while b + right < len(text) and text[b + right] == "*":
        right += 1
    return left, right


def _has(text: str, part: Part, kind: str) -> bool:
    """Is ``part`` already wrapped in ``kind`` (its delimiters right outside it)?"""
    a, b = part.start, part.end
    if kind in ("bold", "italic"):
        left, right = _stars(text, a, b)
        n = min(left, right)
        return n >= 2 if kind == "bold" else n in (1, 3)
    opening, closing = INLINE[kind]
    return text[a - len(opening) : a] == opening and text[b : b + len(closing)] == closing


def _inner(text: str, part: Part, kind: str) -> Part:
    """A selected part that holds its own delimiters (``==word==`` selected whole) as the words
    inside them, so it counts as marked and unmarks cleanly."""
    a, b = part.start, part.end
    if kind in ("bold", "italic"):
        lead = len(text[a:b]) - len(text[a:b].lstrip("*"))
        trail = len(text[a:b]) - len(text[a:b].rstrip("*"))
        n = min(lead, trail)
        want = 2 if kind == "bold" else 1
        if n >= want and b - a > 2 * n:
            return Part(a + n, b - n)
        return part
    opening, closing = INLINE[kind]
    wrapped = text.startswith(opening, a) and text.endswith(closing, a, b)
    if wrapped and b - a > len(opening) + len(closing):
        return Part(a + len(opening), b - len(closing))
    return part


def _inline(text: str, start: int, end: int, kind: str) -> TextEdit | None:
    parts = [_inner(text, p, kind) for p in _parts(text, start, end)]
    if not parts:
        return None
    opening, closing = INLINE[kind]
    remove = all(_has(text, p, kind) for p in parts)
    changes: list[TextChange] = []
    for p in parts:
        if remove:
            changes.append(TextChange(p.start - len(opening), p.start, ""))
            changes.append(TextChange(p.end, p.end + len(closing), ""))
        elif not _has(text, p, kind):
            changes.append(TextChange(p.start, p.start, opening))
            changes.append(TextChange(p.end, p.end, closing))
    return _with_selection(changes, parts[0].start, parts[-1].end)


def _map(changes: list[TextChange], pos: int, assoc: int) -> int:
    """``pos`` in the text after ``changes`` (non-overlapping, in the old text's offsets).
    ``assoc`` > 0: text inserted exactly at ``pos`` goes before it, else after it."""
    out = pos
    for c in changes:
        delta = len(c.insert) - (c.end - c.start)
        if c.end < pos or (c.end == pos and (c.start < c.end or assoc > 0)):
            out += delta
        elif c.start < pos < c.end:  # inside a replaced range: to its start (or end)
            out += c.start - pos + (len(c.insert) if assoc > 0 else 0)
    return out


def _with_selection(changes: list[TextChange], first: int, last: int) -> TextEdit:
    """The edit, with the selection kept on the same words: an opening inserted at ``first``
    stays outside it (before), a closing inserted at ``last`` too (after)."""
    return TextEdit(tuple(changes), _map(changes, last, -1), _map(changes, first, 1))


# ---- colour -------------------------------------------------------------------------------------


def color_code(name: str) -> str | None:
    """A palette name or a ``#rgb`` / ``#rrggbb`` code -> what to write in the span; None if
    unknown. A palette colour is written by its CSS name (``color:red``, user 2026-11-22: readable
    in the file, coloured in other apps), also when given as its palette code."""
    low = name.lower()
    if low in COLORS:
        return low
    if low in _NAME_OF:
        return _NAME_OF[low]
    return low if re.fullmatch(r"#[0-9a-f]{3}(?:[0-9a-f]{3})?", low) else None


def _span_around(text: str, part: Part) -> tuple[int, str] | None:
    """The colour span right around ``part``: (where its opening tag starts, its colour)."""
    if text[part.end : part.end + len(_SPAN_CLOSE)] != _SPAN_CLOSE:
        return None
    lt = text.rfind("<span", 0, part.start)
    if lt < 0:
        return None
    m = _SPAN_OPEN.match(text[lt : part.start])
    if m is None:
        return None
    code = m.group(1).lower()
    return lt, _NAME_OF.get(code, code)  # an older span's palette code counts as its name


def _color(text: str, start: int, end: int, color: str | None) -> TextEdit | None:
    """Colour the words (``color``: palette name or code), recolour them, or (``None`` / the colour
    they already have) take the colour off."""
    parts = _parts(text, start, end)
    if not parts:
        return None
    code = color_code(color) if color else None
    spans = [_span_around(text, p) for p in parts]
    same = all(s is not None and s[1] == code for s in spans)
    changes: list[TextChange] = []
    for p, span in zip(parts, spans, strict=True):
        if span is not None:  # take the old span off (and maybe put a new one on)
            off = code is None or same
            changes.append(TextChange(span[0], p.start, "" if off else _open(code or "")))
            changes.append(TextChange(p.end, p.end + len(_SPAN_CLOSE), "" if off else _SPAN_CLOSE))
        elif code is not None:
            changes.append(TextChange(p.start, p.start, _open(code)))
            changes.append(TextChange(p.end, p.end, _SPAN_CLOSE))
    return _with_selection(changes, parts[0].start, parts[-1].end) if changes else None


def _open(code: str) -> str:
    return f'<span style="color:{code}">'


# ---- links and comments -------------------------------------------------------------------------

_LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\n]*)\)")
_WIKI = re.compile(r"\[\[([^\]|\n]+)(?:\|([^\]\n]*))?\]\]")


def _link(text: str, start: int, end: int, target: str | None) -> TextEdit | None:
    """Make the words a link to ``target`` (a URL, or a note as ``[[note]]``); words that are a
    link already (or ``target`` None) become plain words."""
    parts = _parts(text, start, end)
    if not parts:
        return None
    a, b = parts[0].start, parts[-1].end
    for rx in (_LINK, _WIKI):  # the selection is (inside) one link: unlink it
        for m in rx.finditer(text, max(0, text.rfind("\n", 0, a) + 1)):
            if m.start() > b:
                break
            if m.start() <= a and b <= m.end():
                words = m.group(1) if rx is _LINK else (m.group(2) or m.group(1))
                at = m.start()
                return TextEdit((TextChange(at, m.end(), words),), at + len(words), at)
    if not target:
        return None
    words = text[a:b]
    if "\n" in words:
        return None  # a link is one line of text
    target = target.strip()
    if target.startswith("[[") and target.endswith("]]"):
        note = target[2:-2]
        insert = f"[[{note}]]" if note == words else f"[[{note}|{words}]]"
        return TextEdit((TextChange(a, b, insert),), a + len(insert), a)
    url = target.replace(" ", "%20").replace(")", "%29")
    return _with_selection([TextChange(a, a, "["), TextChange(b, b, f"]({url})")], a, b)


def clean_comment(comment: str) -> str:
    """One line, and never a ``%%`` that would end the comment early."""
    one = " ".join(comment.split())
    while "%%" in one:
        one = one.replace("%%", "%")
    return one.strip("%").strip()


def _comment(text: str, start: int, end: int, comment: str | None) -> TextEdit | None:
    """``comment`` may open with its pin colour (``{red} words``, as written in the file)."""
    parts = _parts(text, start, end)
    color, raw = split_comment(comment or "")
    body = clean_comment(raw)
    if not parts or not body:
        return None
    a, b = parts[0].start, parts[-1].end
    return TextEdit((TextChange(b, b, comment_mark(body, color)),), b, a)


# A comment's pin colour (user 2026-11-20): grey without a mark, else ``%%{red} text%%``.
COMMENT_COLORS = ("red", "yellow", "green")
_COMMENT_COLOR = re.compile(r"^\{(" + "|".join(COMMENT_COLORS) + r")\}\s*")


def split_comment(raw: str) -> tuple[str, str]:
    """A comment's inside as ``(colour, text)``; colour ``""`` = the default grey."""
    m = _COMMENT_COLOR.match(raw.strip())
    if m is None:
        return "", raw.strip()
    return m.group(1), raw.strip()[m.end() :].strip()


def comment_mark(body: str, color: str = "") -> str:
    """The ``%%…%%`` for a comment's text and pin colour (unknown colour: grey)."""
    tag = f"{{{color}}} " if color in COMMENT_COLORS else ""
    return f"%%{tag}{body}%%"


@dataclass(frozen=True, slots=True)
class Comment:
    """A ``%%comment%%`` in the note: where the mark is, what it says, its pin colour."""

    start: int
    end: int
    body: str
    color: str = ""


def comments(text: str) -> list[Comment]:
    """Every inline comment of the note (outside code is the editor's business: it hides only
    those its parser sees)."""
    return [
        Comment(m.start(), m.end(), *reversed(split_comment(m.group(1))))
        for m in COMMENT.finditer(text)
    ]


def set_comment(text: str, at: int, body: str, color: str | None = None) -> TextEdit | None:
    """Change the comment that starts at ``at`` (empty ``body``: delete it). ``color`` None keeps
    the comment's pin colour; ``""`` makes it grey."""
    m = COMMENT.match(text, at)
    if m is None:
        return None
    old_color, _ = split_comment(m.group(1))
    new = clean_comment(split_comment(body)[1])
    insert = comment_mark(new, old_color if color is None else color) if new else ""
    return TextEdit((TextChange(m.start(), m.end(), insert),), m.start() + len(insert))


# ---- line items ---------------------------------------------------------------------------------


def _line_starts(text: str, start: int, end: int) -> list[int]:
    starts = [text.rfind("\n", 0, start) + 1]
    pos = text.find("\n", starts[0])
    while 0 <= pos < end and pos + 1 <= len(text):
        if pos + 1 == end and end > start:
            break  # a selection ending at a line start does not take that line
        starts.append(pos + 1)
        pos = text.find("\n", pos + 1)
    return starts


def _marker_of(kind: str, n: int) -> str:
    return {
        "bullet": "- ",
        "numbered": f"{n}. ",
        "todo": "- [ ] ",
        "h1": "# ",
        "h2": "## ",
        "h3": "### ",
    }[kind]


def _kind_of(marker: str) -> str:
    """Which line kind a line's marker is ("" when it has none)."""
    if not marker:
        return ""
    if _TASK.fullmatch(marker):
        return "todo"
    if _BULLET.fullmatch(marker):
        return "bullet"
    if _NUMBER.fullmatch(marker):
        return "numbered"
    if _HEADING.fullmatch(marker):
        return f"h{min(len(marker.rstrip()), 6)}" if len(marker.rstrip()) <= 3 else "h"
    return ""


def _lines(text: str, start: int, end: int, kind: str) -> TextEdit | None:
    rows = []
    for s in _line_starts(text, start, end):
        e = text.find("\n", s)
        e = len(text) if e < 0 else e
        m = _PREFIX.match(text, s, e)
        assert m is not None
        rows.append((s, e, m.group(1), m.group(2), m.group(3) or ""))
    filled = [r for r in rows if text[r[0] : r[1]].strip()]
    if not filled:
        filled = rows[:1]
    changes: list[TextChange] = []
    if kind == "quote":
        remove = all(r[2] for r in filled)
        for s, _e, quote, _indent, _marker in filled:
            if remove:
                drop = re.match(r"[ \t]*>[ \t]?", quote)
                assert drop is not None
                changes.append(TextChange(s, s + drop.end(), ""))
            elif not quote:  # a line already quoted stays one level deep
                changes.append(TextChange(s, s, "> "))
    else:
        remove = all(_kind_of(r[4]) == kind for r in filled)
        for n, (s, _e, quote, indent, marker) in enumerate(filled, start=1):
            at = s + len(quote) + len(indent)
            if remove:
                changes.append(TextChange(at, at + len(marker), ""))
            else:
                changes.append(TextChange(at, at + len(marker), _marker_of(kind, n)))
    first, last = filled[0][0], filled[-1][1]
    after_last = last + sum(len(c.insert) - (c.end - c.start) for c in changes)
    return TextEdit(tuple(changes), after_last, first)


# ---- export -------------------------------------------------------------------------------------

_CODE_SPAN = re.compile(r"(`+)(?:.+?)\1")
_HIGHLIGHT = re.compile(r"(?<!=)==(?=[^\s=])(.+?)(?<=[^\s=])==(?!=)")
_RAW_BLOCKS = {
    "fence",
    "code_block",
    "math_block",
    "math_block_label",
    "front_matter",
    "html_block",
}


def _raw_lines(text: str) -> set[int]:
    """Line numbers (0-based) of code, math and front matter: written out as they are."""
    from paper_pile.core.parser import parse  # local: the parser is heavy to import

    lines: set[int] = set()
    for tok in parse(text):
        if tok.type in _RAW_BLOCKS and tok.map:
            lines.update(range(tok.map[0], tok.map[1]))
    return lines


def _line_comment_at(line: str, pos: int, part: str) -> int | None:
    """Where a ``//`` comment starts in ``part`` (``line[pos:…]``): at the line's start or after
    a space or tab — never glued to text (``https://``) or to a code span before it."""
    for m in re.finditer("//", part):
        i = m.start()
        before = part[i - 1] if i > 0 else (line[pos - 1] if pos > 0 else "")
        if before in ("", " ", "\t"):
            return i
    return None


def _strip_line(line: str, keep_highlights: bool) -> str:
    """One line without its comments (outside code spans), highlights unwrapped if asked."""
    out: list[str] = []
    pos = 0
    spans = [(m.start(), m.end()) for m in _CODE_SPAN.finditer(line)] + [(len(line), len(line))]
    for start, end in spans:
        part = COMMENT.sub("", line[pos:start])
        cut = _line_comment_at(line, pos, part)
        if cut is not None:
            part = part[:cut]
        out.append(part if keep_highlights else _HIGHLIGHT.sub(r"\1", part))
        if cut is not None:
            return "".join(out).rstrip()
        out.append(line[start:end])
        pos = end
    return "".join(out)


def strip_for_export(text: str, *, keep_highlights: bool = True) -> str:
    """The note as it is exported (PLAN §4.38): ``%%comments%%`` and ``//`` comments removed
    (a line that was only a comment goes), ``==highlights==`` unwrapped unless kept. Code, math
    and front matter are left as they are."""
    raw = _raw_lines(text)
    out: list[str] = []
    for n, line in enumerate(text.split("\n")):
        if n in raw:
            out.append(line)
            continue
        new = _strip_line(line, keep_highlights)
        if new.strip() or not line.strip():
            out.append(new)
        # else: the line held only comments — dropped, so it cannot split a paragraph
    return "\n".join(out)


# ---- entry point --------------------------------------------------------------------------------


def apply(text: str, start: int, end: int, kind: str, arg: str | None = None) -> TextEdit | None:
    """The edit for menu item ``kind`` on ``text[start:end]``; None when it does nothing there.
    ``arg``: the colour (``color``), the link target (``link``: a URL or ``[[note]]``), the
    comment's text (``comment``)."""
    start, end = sorted((max(0, start), min(len(text), end)))
    if kind in INLINE:
        return _inline(text, start, end, kind)
    if kind == "color":
        return _color(text, start, end, arg)
    if kind == "link":
        return _link(text, start, end, arg)
    if kind == "comment":
        return _comment(text, start, end, arg)
    if kind in LINE_KINDS:
        return _lines(text, start, end, kind)
    raise ValueError(f"unknown format {kind!r}")
