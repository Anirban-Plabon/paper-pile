"""AI replacements as proposals the user approves (PLAN §4.26): the AI changes the user's own
text only through a diff, unless the user chose *Apply at once* (inserts at the caret are the
other kind of change, see ``edits.py``).

A proposal replaces a region of a note (``start`` and the text it held, ``old``) with new text,
split by lines into hunks the editor shows as a diff (removed lines red, added lines green) and
the user accepts or rejects one by one or all at once. Offsets are code points of the note's
text. Before anything is applied the region is looked for again: where it was, or once anywhere
else in the note (the user typed above it); if it is gone or appears twice the proposal is out
of date and nothing is applied. No UI imports here.
"""

import difflib
import itertools
from dataclasses import dataclass, field, replace

_ids = itertools.count(1)


@dataclass(frozen=True, slots=True)
class Hunk:
    id: int
    start: int  # in the note's text
    end: int
    old: str
    new: str


@dataclass(frozen=True, slots=True)
class Proposal:
    id: int
    path: str
    start: int  # the region in the note
    old: str  # its text now (accepted hunks included)
    hunks: tuple[Hunk, ...] = field(default=())

    @property
    def end(self) -> int:
        return self.start + len(self.old)


@dataclass(frozen=True, slots=True)
class Change:
    start: int
    end: int
    insert: str


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def propose(path: str, text: str, start: int, end: int, new: str) -> Proposal | None:
    """A proposal to replace ``text[start:end]`` by ``new`` (None when nothing changes)."""
    old = text[start:end]
    if old.endswith("\n") and not new.endswith("\n"):
        new += "\n"  # keep the region's line break: the diff is about the lines
    if old == new:
        return None
    a, b = _lines(old), _lines(new)
    offsets = [0, *itertools.accumulate(len(line) for line in a)]
    hunks: list[Hunk] = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunks.append(
            Hunk(
                next(_ids),
                start + offsets[i1],
                start + offsets[i2],
                "".join(a[i1:i2]),
                "".join(b[j1:j2]),
            )
        )
    return Proposal(next(_ids), path, start, old, tuple(hunks)) if hunks else None


def locate(proposal: Proposal, text: str) -> Proposal | None:
    """``proposal`` moved to where its region is in ``text`` now; None when out of date."""
    if text[proposal.start : proposal.end] == proposal.old:
        return proposal
    first = text.find(proposal.old)
    if not proposal.old or first < 0 or text.find(proposal.old, first + 1) >= 0:
        return None
    delta = first - proposal.start
    moved = tuple(replace(h, start=h.start + delta, end=h.end + delta) for h in proposal.hunks)
    return replace(proposal, start=first, hunks=moved)


def accept(
    proposal: Proposal, text: str, hunk_ids: set[int] | None = None
) -> tuple[list[Change], Proposal | None] | None:
    """Apply the hunks ``hunk_ids`` (all when None) to ``text``: the changes to make and what is
    left of the proposal (None when nothing is). None when the proposal is out of date."""
    here = locate(proposal, text)
    if here is None:
        return None
    take = [h for h in here.hunks if hunk_ids is None or h.id in hunk_ids]
    changes = [Change(h.start, h.end, h.new) for h in take]
    rest: list[Hunk] = []
    shift = 0
    region = here.old
    for h in here.hunks:
        if h in take:
            at = h.start - here.start + shift
            region = region[:at] + h.new + region[at + len(h.old) :]
            shift += len(h.new) - len(h.old)
        else:
            rest.append(replace(h, start=h.start + shift, end=h.end + shift))
    left = replace(here, old=region, hunks=tuple(rest)) if rest else None
    return changes, left


def reject(proposal: Proposal, hunk_id: int | None = None) -> Proposal | None:
    """Drop one hunk (or all when None); None when nothing is left."""
    if hunk_id is None:
        return None
    rest = tuple(h for h in proposal.hunks if h.id != hunk_id)
    return replace(proposal, hunks=rest) if rest else None


def apply_changes(text: str, changes: list[Change]) -> str:
    """``text`` with ``changes`` made (they do not overlap)."""
    for c in sorted(changes, key=lambda c: c.start, reverse=True):
        text = text[: c.start] + c.insert + text[c.end :]
    return text
