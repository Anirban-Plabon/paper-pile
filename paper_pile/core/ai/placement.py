"""Where an answer command's text goes (``docs/AI_EDITS.md`` §6.1): after the top-level block
that holds the end of the selection — a whole list, quote, table or code block, never inside
one — or at the end of the note; the section level its headings stay below; the list marker it
must not start with (so it does not join the user's list); and whether the section already has
such an answer. No UI imports.
"""

import re
from dataclasses import dataclass

from paper_pile.core.ai.blocks import block_map
from paper_pile.core.ai.cleanup import heading_floor

_MARKER = re.compile(r"^([-*+])[ \t]")
# headings or bold labels that already hold what a command writes
_ALREADY = {
    "ai-summarize": ("summary", "tl;dr", "tldr"),
    "ai-outline": ("outline",),
    "ai-explain": ("explanation",),
}


@dataclass(frozen=True, slots=True)
class AnswerPoint:
    offset: int  # where the answer is inserted
    lead: str  # what goes before it (a blank line)
    heading_floor: int  # the section's level there: the answer's headings stay below it
    avoid_bullet: str = ""  # the list just above uses this marker: the answer uses another


def answer_point(note: str, start: int, end: int, *, whole: bool = False) -> AnswerPoint:
    """Where the answer about ``note[start:end]`` goes (``whole``: the note's body)."""
    if whole or not note[start:end].strip():
        at = len(note.rstrip("\n"))  # before the note's last line break: one blank line above
        lead = "\n\n" if note[:at].strip() else ""
        return AnswerPoint(at, lead, heading_floor(note, at))
    blocks = [b for b in block_map(note) if b.kind != "front_matter"]
    last = end - 1 if end > start else end
    holding = [b for b in blocks if b.start <= last]
    if not holding:
        return AnswerPoint(end, "\n\n", heading_floor(note, end))
    block = holding[-1]
    if block.list_id:  # after the whole list, never between its items
        block = [b for b in blocks if b.list_id == block.list_id][-1]
    at = max(block.end, end)
    bullet = ""
    if block.list_id:
        first = next(b for b in blocks if b.list_id == block.list_id)
        m = _MARKER.match(note[first.start : first.end])
        bullet = m.group(1) if m else ""
    return AnswerPoint(at, "\n\n", heading_floor(note, at), bullet)


def other_bullet(bullet: str) -> str:
    """The marker an answer's list uses next to a list marked ``bullet``."""
    return "*" if bullet == "-" else "-"


def already_answered(note: str, at: int, command_id: str) -> str:
    """ "This note already has a Summary (line 3)." when the section around offset ``at`` has a
    heading or bold label for what ``command_id`` writes; "" otherwise (the answer is still
    written: this is only for the user to know)."""
    words = _ALREADY.get(command_id)
    if not words:
        return ""
    line_no = note.count("\n", 0, at) + 1
    blocks = block_map(note)
    floor = heading_floor(note, at)
    start = 0
    end = len(note)
    for b in blocks:  # the section: from its heading to the next heading at its level or above
        if b.kind != "heading":
            continue
        if b.line <= line_no and b.level == floor:
            start = b.start
        elif b.line > line_no and (not floor or b.level <= floor):
            end = b.start
            break
    for b in blocks:
        if start <= b.start < end:
            label = _label(note[b.start : b.end].split("\n", 1)[0])
            if label.lower() in words:
                return f"This note already has a {label} (line {b.line})."
    return ""


def _label(line: str) -> str:
    """A heading's text, or a leading bold label (``**Summary:**``, also in a quote)."""
    text = line.strip().removeprefix(">").strip()
    m = re.match(r"#{1,6}\s+(.*?)\s*#*$", text) or re.match(r"\*\*([^*\n]+?)\*\*", text)
    return m.group(1).strip(" :") if m else ""
