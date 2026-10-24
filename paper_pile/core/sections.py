"""The note header's sections: a note is read in ``#`` / ``##`` sections. The header names the
note (its ``title`` property, else its file name) and the section at the top of the view, and its
‹ › buttons jump to the previous / next section start."""

from paper_pile.core.parser import Heading, front_matter, headings, section_at
from paper_pile.core.titles import note_name

SECTION_LEVELS = 2  # `#` and `##` start a section


def note_title(text: str, path: str) -> str:
    """The ``title`` property when it is set, else the note's name."""
    fm = front_matter(text)
    title = fm.data.get("title") if fm is not None and not fm.error else None
    return (
        str(title).strip()
        if isinstance(title, str | int | float) and str(title).strip()
        else note_name(path)
    )


def section_heads(text: str) -> list[Heading]:
    return [h for h in headings(text) if h.level <= SECTION_LEVELS]


def current_section(heads: list[Heading], top: int) -> Heading | None:
    """The section that holds line ``top`` (the line at the top of the view)."""
    at = section_at(heads, top)
    return heads[at] if at is not None else None


def previous_start(heads: list[Heading], top: int) -> int | None:
    """Where ‹ goes: the start of the section on screen, or the one before when the view is
    already at its start."""
    at = section_at(heads, top)
    if at is not None and heads[at].line >= top - 1:  # at the heading itself (or just above it)
        at -= 1
    return heads[at].line if at is not None and at >= 0 else None


def next_start(heads: list[Heading], top: int) -> int | None:
    """Where › goes: the first section that starts below line ``top``."""
    return next((h.line for h in heads if h.line > top), None)
