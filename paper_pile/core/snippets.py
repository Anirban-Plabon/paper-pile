"""The line of context shown for a backlink: plain text with the link itself marked."""

import re
from dataclasses import dataclass

from paper_pile.core.parser import plain_line

_BLOCK_MARKER = re.compile(r"^\s*(?:>\s*)*(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+|#{1,6}\s+)?")


@dataclass(frozen=True, slots=True)
class Snippet:
    before: str
    hit: str  # the link as the reader sees it ("" if it could not be found)
    after: str

    @property
    def text(self) -> str:
        return self.before + self.hit + self.after


def link_snippet(text: str, line: int, kind: str = "", raw: str = "", width: int = 140) -> Snippet:
    """Context for the link ``raw`` (``kind`` ``wiki``/``md``) on ``line`` of ``text``: list,
    quote and heading markers and all markdown syntax removed, whitespace collapsed, and cut to
    about ``width`` characters around the link."""
    lines = text.splitlines()
    source = lines[line - 1] if 1 <= line <= len(lines) else ""
    plain = plain_line(_BLOCK_MARKER.sub("", source), kind, raw)
    clean = " ".join(plain.text.split())
    hit = plain.hit
    if hit is not None:  # whitespace collapsing may have moved it: find it again in the result
        shown = " ".join(plain.text[hit[0] : hit[1]].split())
        start = clean.find(shown) if shown else -1
        hit = (start, start + len(shown)) if start >= 0 else None
    if len(clean) > width:
        lo = 0
        if hit is not None and hit[1] > width - 10:
            lo = max(0, hit[0] - width // 3)
        clean_cut = clean[lo : lo + width - 1].rstrip()
        prefix = "…" if lo else ""
        suffix = "…" if lo + width - 1 < len(clean) else ""
        if hit is not None:
            hit = (
                hit[0] - lo + len(prefix),
                min(hit[1] - lo + len(prefix), len(prefix) + len(clean_cut)),
            )
        clean = prefix + clean_cut + suffix
    if hit is None or hit[0] >= hit[1] or hit[0] >= len(clean):
        return Snippet(clean, "", "")
    return Snippet(clean[: hit[0]], clean[hit[0] : hit[1]], clean[hit[1] :])
