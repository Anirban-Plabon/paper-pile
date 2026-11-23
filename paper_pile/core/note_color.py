"""A note's colour (user 2026-11-22, PLAN §4.39): ``color: <name>`` in its front matter.

One of the eight palette names of ``core.formatting.COLORS``; the app tints the note's tab and its
properties box with it. It lives in the file, so it travels with the note; other apps see an
ordinary property. Pure text functions, cheap enough to run on every edit (a line scan of the
front matter, no YAML parse).
"""

import re

from paper_pile.core.formatting import COLORS
from paper_pile.core.parser import front_matter_lines

NOTE_COLORS: tuple[str, ...] = tuple(COLORS)
HEAD_LINES = 200  # a colour further down a front matter is not looked for
_LINE = re.compile(r"^color:[ \t]*([\"']?)([A-Za-z]*)\1[ \t]*$")


def _lines(text: str) -> tuple[list[str], int]:
    """The text's lines (newline kept) and how many the front matter takes (0: none)."""
    return text.splitlines(keepends=True), front_matter_lines(text)


def note_color(text: str) -> str:
    """The note's palette colour name, ``""`` when it has none (or an unknown one). Reads only
    the front matter's lines (it runs for every open tab on each refresh)."""
    if not text.startswith("---"):
        return ""
    lines = text.split("\n", HEAD_LINES)[:HEAD_LINES]
    if lines[0].rstrip() != "---":
        return ""
    found = ""
    for line in lines[1:]:
        line = line.rstrip("\r")
        if line.rstrip() == "---":  # closed: a real front matter
            return "" if found == "-" else found
        m = _LINE.match(line)
        if m and not found:
            name = m.group(2).lower()
            found = name if name in COLORS else "-"
    return ""  # never closed: no front matter (the parser's rule)


def with_color(text: str, color: str) -> str:
    """``text`` with its colour set to ``color`` (``""`` removes it). A note without front
    matter gets one; a front matter left empty by the removal goes."""
    if color and color not in COLORS:
        raise ValueError(f"unknown colour: {color!r}")
    nl = "\r\n" if "\r\n" in text else "\n"
    lines, count = _lines(text)
    if not count:
        if not color:
            return text
        return f"---{nl}color: {color}{nl}---{nl}{nl if text.strip() else ''}{text}"
    head = lines[1 : count - 1]
    at = next((i for i, line in enumerate(head) if _LINE.match(line.rstrip("\r\n"))), None)
    if color:
        new = f"color: {color}{nl}"
        if at is None:
            head.append(new)
        else:
            head[at] = new
    elif at is not None:
        del head[at]
    else:
        return text
    rest = lines[count:]
    if not head:  # the colour was its only property: no empty block left behind
        if rest and not rest[0].strip():
            rest = rest[1:]
        return "".join(rest)
    closing = lines[count - 1]
    if not closing.endswith(("\n", "\r")):
        closing += nl if rest else ""
    return "".join([lines[0], *head, closing, *rest])
