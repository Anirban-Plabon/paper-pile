"""Tidy a note ("Tidy note" button): a clean, consistent layout that MEANS the same.

Block boundaries come from the note parser (``core/parser.py``), never from guessing:

* exactly one empty line between blocks (headings, paragraphs, lists, quotes, code, math,
  tables, rules); none at the start, one newline at the end;
* trailing spaces removed (two or more before a line of the same paragraph are a line break:
  kept as exactly two);
* inside lists and quotes, runs of empty lines become one;
* "lazy" lines (written without ``>`` / indentation but belonging to a quote or list item in
  markdown) get their ``> `` / indentation, so what the note means is now what it shows;
* headings get one space after the ``#``s (a one-line ``Title`` over ``===`` / ``---`` becomes
  ``# Title`` / ``## Title``), rules (``***``, ``___``) become ``---``, tables are
  aligned (only when no cell would be lost).

Never changed: front matter, fenced / indented code, ``$$`` math, and any line the parser
does not place in a block (link definitions, footnotes) is kept as written. Pure: str -> str.
"""

import re
from dataclasses import dataclass, field

from markdown_it.token import Token

from paper_pile.core.parser import parse
from paper_pile.core.tables import format_table, parse_table, split_row

_VERBATIM = {"fence", "code_block", "math_block", "math_block_label", "front_matter"}
_BLOCK_OPEN = {
    "paragraph_open": "paragraph",
    "heading_open": "heading",
    "bullet_list_open": "list",
    "ordered_list_open": "list",
    "blockquote_open": "quote",
    "table_open": "table",
}
_LIST_MARK = re.compile(r"^([ \t]*)(?:[-*+]|\d{1,9}[.)])([ \t]+|$)")
_HEADING = re.compile(r"^(\s{0,3}#{1,6})[ \t]+")
_HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_QUOTE = re.compile(r"^[ \t]{0,3}>")


@dataclass
class _Block:
    kind: str  # paragraph heading list quote table hr verbatim raw front_matter
    start: int  # first line (0-based)
    end: int  # one past the last line
    lines: list[str] = field(default_factory=list)


def tidy(text: str) -> str:
    """``text`` laid out cleanly (see the module docstring). Line endings are kept."""
    newline = "\r\n" if "\r\n" in text else "\n"
    src = text.replace("\r\n", "\n")
    lines = src.split("\n")
    tokens = parse(src)
    protected = _protected_lines(tokens)
    blocks = _blocks(tokens, lines)
    out: list[str] = []
    for i, block in enumerate(blocks):
        body = _clean(block, lines, protected)
        if not body:
            continue
        if out:
            # front matter keeps whatever followed it (none or one empty line), all else gets one
            gap = 1
            if blocks[i - 1].kind == "front_matter":
                gap = 1 if not lines[blocks[i - 1].end].strip() else 0
            out.extend([""] * gap)
        out.extend(body)
    result = "\n".join(out).rstrip("\n")
    return (result + "\n").replace("\n", newline) if result else ""


def _protected_lines(tokens: list[Token]) -> set[int]:
    """Lines that are code, math or front matter at any depth: kept byte for byte."""
    keep: set[int] = set()
    for t in tokens:
        if t.type in _VERBATIM and t.map:
            keep.update(range(t.map[0], t.map[1]))
    return keep


def _blocks(tokens: list[Token], lines: list[str]) -> list[_Block]:
    """The note's top-level blocks in order; lines in no block (other than empty ones) become
    "raw" blocks so nothing is ever dropped."""
    found: list[_Block] = []
    for t in tokens:
        if t.level != 0 or not t.map:
            continue
        if t.type in _BLOCK_OPEN:
            kind = _BLOCK_OPEN[t.type]
        elif t.type == "hr":
            kind = "hr"
        elif t.type == "front_matter":
            kind = "front_matter"
        elif t.type in _VERBATIM:
            kind = "verbatim"
        else:
            continue
        found.append(_Block(kind, t.map[0], t.map[1]))
    found.sort(key=lambda b: b.start)
    blocks: list[_Block] = []
    at = 0
    for block in [*found, _Block("end", len(lines), len(lines))]:
        if block.start > at:  # uncovered lines: keep each run of non-empty ones as written
            run: list[int] = []
            for n in range(at, block.start):
                if lines[n].strip():
                    run.append(n)
                elif run:
                    blocks.append(_Block("raw", run[0], run[-1] + 1))
                    run = []
            if run:
                blocks.append(_Block("raw", run[0], run[-1] + 1))
        if block.kind != "end":
            blocks.append(block)
        at = max(at, block.end)
    return blocks


def _clean(block: _Block, lines: list[str], protected: set[int]) -> list[str]:
    src = lines[block.start : block.end]
    if block.kind in ("verbatim", "front_matter"):
        return _trim_blank_edges(src)
    if block.kind == "heading" and len(src) == 1:
        return [_HEADING.sub(lambda m: m.group(1) + " ", src[0].rstrip())]
    if block.kind == "heading" and len(src) == 2 and src[0].strip():
        # "Title" over "===" / "---" (often a divider typed straight under text): the same
        # heading, written the way it reads
        level = "#" if src[1].strip().startswith("=") else "##"
        return [f"{level} {src[0].strip()}"]
    if block.kind == "hr":
        return ["---"] if _HR.match(src[0]) else [src[0].rstrip()]
    if block.kind == "table":
        return _table(src)
    body = _strip_trailing(src, block.start, protected)
    if block.kind == "quote":
        body = _quote_lazy_lines(body, block.start, protected)
    elif block.kind == "list":
        body = _list_lazy_lines(body, block.start, protected)
    return _trim_blank_edges(_single_blanks(body, block.start, protected))


def _strip_trailing(src: list[str], first: int, protected: set[int]) -> list[str]:
    out = []
    for i, line in enumerate(src):
        if first + i in protected:
            out.append(line)
            continue
        stripped = line.rstrip(" \t")
        following = src[i + 1] if i + 1 < len(src) else ""
        hard_break = (
            line.endswith("  ")
            and following.strip()
            and not following.lstrip().startswith(("-", "*", "+", "#", "```", "~~~"))
        )
        out.append(stripped + "  " if hard_break and stripped.strip() else stripped)
    return out


def _quote_lazy_lines(body: list[str], first: int, protected: set[int]) -> list[str]:
    """A quote holds no empty lines, so a line without ``>`` in it is a lazy one: add the mark."""
    return [
        line if first + i in protected or not line.strip() or _QUOTE.match(line) else "> " + line
        for i, line in enumerate(body)
    ]


def _list_lazy_lines(body: list[str], first: int, protected: set[int]) -> list[str]:
    """A line straight under a list item's text that is indented less than that text continues
    the item's paragraph anyway (markdown's lazy continuation): indent it to the text."""
    out: list[str] = []
    column: int | None = None  # where the open paragraph's text starts
    for i, line in enumerate(body):
        if first + i in protected or not line.strip():
            column = None
            out.append(line)
            continue
        mark = _LIST_MARK.match(line)
        if mark:
            column = len(mark.group(0))
            if not mark.group(2):  # "-" alone on its line: text starts after one space
                column += 1
            out.append(line)
            continue
        indent = len(line) - len(line.lstrip(" "))
        if column is not None and indent < column and not _starts_block(line):
            line = " " * column + line.lstrip(" \t")
        elif column is None:
            column = indent
        out.append(line)
    return out


def _starts_block(line: str) -> bool:
    s = line.lstrip()
    return s.startswith((">", "#", "```", "~~~", "|", "$$")) or bool(_HR.match(line))


def _single_blanks(body: list[str], first: int, protected: set[int]) -> list[str]:
    out: list[str] = []
    for i, line in enumerate(body):
        if not line.strip() and first + i not in protected and out and not out[-1].strip():
            continue
        out.append(line if line.strip() or first + i in protected else "")
    return out


def _trim_blank_edges(body: list[str]) -> list[str]:
    start, end = 0, len(body)
    while start < end and not body[start].strip():
        start += 1
    while end > start and not body[end - 1].strip():
        end -= 1
    return body[start:end]


def _table(src: list[str]) -> list[str]:
    """Aligned, if that keeps every cell (a row with more cells than the header is left as is)."""
    body = [line.rstrip() for line in _trim_blank_edges(src)]
    table = parse_table("\n".join(body))
    if table is None:
        return body
    width = len(table.header)
    if any(len(split_row(line.lstrip(" \t>"))) > width for line in body[2:]):
        return body
    return format_table(table).rstrip("\n").split("\n")
