"""The note as numbered blocks for AI edits (PLAN §4.29, ``docs/AI_EDITS.md`` §4.2).

The model names *where* to change the note by block id (``B7``); Python knows the exact text
behind each id, so the model never has to copy old text or count lines. Top-level list items are
blocks of their own (so a list can grow by one item); a table is one block. Ids belong to one
snapshot of the note: an edit is placed by the block's text, re-found when it is applied. Pure;
no UI imports.
"""

from dataclasses import dataclass

from paper_pile.core.blocks import RawBlock, top_blocks
from paper_pile.core.parser import parse

FIXED_KINDS = frozenset({"code", "math", "diagram", "front_matter"})  # never rewritten unasked


@dataclass(frozen=True, slots=True)
class Block:
    id: str  # "B7" (document order, this snapshot only); the front matter is "B0"
    kind: str  # heading paragraph item table quote code math diagram hr raw front_matter
    start: int  # code points in the note
    end: int  # after the block's last character (its last line break not included)
    line: int  # first line, 1-based
    level: int  # a heading's level; 0 for the rest
    path: tuple[str, ...]  # the headings it is under (a heading: its parents and itself)
    list_id: str  # items of one list share it ("L3"); "" for other blocks
    fixed: bool  # code, math, diagrams, front matter

    def text(self, note: str) -> str:
        return note[self.start : self.end]


def block_map(note: str) -> list[Block]:
    """``note``'s blocks in order (see the module docstring)."""
    src = note.replace("\r\n", "\n")
    lines = src.split("\n")
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    crlf = src != note  # offsets are into the note as given

    def offset(line: int, *, end: bool = False) -> int:
        """The code point where ``line`` starts (``end``: where the line before it ends)."""
        at = starts[line] - (1 if end else 0)
        return at + (line - (1 if end else 0) if crlf else 0)

    out: list[Block] = []
    path: list[tuple[int, str]] = []  # (level, title) of the headings above
    lists = 0
    n = 1
    tokens = parse(src)
    items = [
        (t.map[0], t.map[1])
        for t in tokens
        if t.type == "list_item_open" and t.level == 1 and t.map
    ]
    for raw in top_blocks(tokens, lines):
        parts = _parts(raw, items)
        list_id = ""
        if raw.kind == "list":
            lists += 1
            list_id = f"L{lists}"
        for first, last in parts:
            last = _trim(lines, first, last)
            if last <= first:
                continue
            kind, level = _kind(raw, list_id)
            if kind == "heading":
                title = lines[first].lstrip("#").strip() or lines[first].strip()
                while path and path[-1][0] >= level:
                    path.pop()
                path.append((level, title))
            block_id = "B0" if kind == "front_matter" else f"B{n}"
            if kind != "front_matter":
                n += 1
            out.append(
                Block(
                    block_id,
                    kind,
                    offset(first),
                    offset(last, end=True),
                    first + 1,
                    level,
                    tuple(t for _, t in path),
                    list_id,
                    kind in FIXED_KINDS,
                )
            )
    return out


def _parts(raw: RawBlock, items: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Line ranges: one per top-level item of a list, else the whole block."""
    if raw.kind != "list":
        return [(raw.start, raw.end)]
    own = [(a, b) for a, b in items if raw.start <= a < raw.end]
    return own or [(raw.start, raw.end)]


def _trim(lines: list[str], first: int, last: int) -> int:
    """``last`` without the empty lines at the end of the range."""
    while last > first and not lines[last - 1].strip():
        last -= 1
    return last


def _kind(raw: RawBlock, list_id: str) -> tuple[str, int]:
    t = raw.token
    if raw.kind == "heading" and t is not None:
        return "heading", int(t.tag[1:]) if t.tag[1:].isdigit() else 1
    if raw.kind == "list":
        return "item", 0
    if raw.kind == "verbatim" and t is not None:
        if t.type.startswith("math"):
            return "math", 0
        info = t.info.strip().split(maxsplit=1)[0].lower() if t.info.strip() else ""
        return ("diagram" if info == "mermaid" else "math" if info == "math" else "code"), 0
    return raw.kind, 0
