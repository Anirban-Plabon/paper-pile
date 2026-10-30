"""A note's top-level blocks, from the note parser (``core/parser.py``), never from guessing.

One splitter for everything that works block by block: *Tidy note* (``tidy.py``) and the AI's
block map (``ai/blocks.py``, PLAN §4.29). Lines the parser places in no block (other than empty
ones) become "raw" blocks, so nothing is ever dropped. Pure; no UI imports.
"""

from dataclasses import dataclass, field

from markdown_it.token import Token

VERBATIM = {"fence", "code_block", "math_block", "math_block_label", "front_matter"}
_BLOCK_OPEN = {
    "paragraph_open": "paragraph",
    "heading_open": "heading",
    "bullet_list_open": "list",
    "ordered_list_open": "list",
    "blockquote_open": "quote",
    "table_open": "table",
}


@dataclass
class RawBlock:
    kind: str  # paragraph heading list quote table hr verbatim raw front_matter
    start: int  # first line (0-based)
    end: int  # one past the last line
    lines: list[str] = field(default_factory=list)
    token: Token | None = None  # the opening token (None for raw blocks)


def top_blocks(tokens: list[Token], lines: list[str]) -> list[RawBlock]:
    """The note's top-level blocks in order (``tokens`` from ``parse``, ``lines`` its lines)."""
    found: list[RawBlock] = []
    for t in tokens:
        if t.level != 0 or not t.map:
            continue
        if t.type in _BLOCK_OPEN:
            kind = _BLOCK_OPEN[t.type]
        elif t.type == "hr":
            kind = "hr"
        elif t.type == "front_matter":
            kind = "front_matter"
        elif t.type in VERBATIM:
            kind = "verbatim"
        else:
            continue
        found.append(RawBlock(kind, t.map[0], t.map[1], token=t))
    found.sort(key=lambda b: b.start)
    blocks: list[RawBlock] = []
    at = 0
    for block in [*found, RawBlock("end", len(lines), len(lines))]:
        if block.start > at:  # uncovered lines: keep each run of non-empty ones as written
            run: list[int] = []
            for n in range(at, block.start):
                if lines[n].strip():
                    run.append(n)
                elif run:
                    blocks.append(RawBlock("raw", run[0], run[-1] + 1))
                    run = []
            if run:
                blocks.append(RawBlock("raw", run[0], run[-1] + 1))
        if block.kind != "end":
            blocks.append(block)
        at = max(at, block.end)
    return blocks
