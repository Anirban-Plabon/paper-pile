"""AI replacements as proposals the user approves (PLAN §4.26, §4.29): the AI changes the user's
own text only through a diff, unless the user chose *Apply at once* (inserts at the caret are the
other kind of change, see ``edits.py``).

A proposal holds one or more *regions* of a note — whole lines around each place the edit
changes ("add the option to the list", "update the count in the intro") — each with the text it
held (``old``) and its line hunks by ``difflib``, which the editor shows as a diff (removed lines
red, added lines green) and the user accepts or rejects one by one or all at once. A hunk carries
the reason the AI gave and what the checks found. Offsets are code points of the note's text.
Before anything is applied each region is looked for again: where it was, or once anywhere else
in the note (the user typed above it); a region that is gone or appears twice is out of date and
nothing of it is applied — the other regions still are. No UI imports here.
"""

import difflib
import itertools
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from paper_pile.core.ai.issues import Issue

_ids = itertools.count(1)
WORD_MARK_LIMIT = 0.6  # above this share of changed words, word marks are noise
_TOKEN = re.compile(r"\s+|[^\W_]+|[^\s\w]|_")


@dataclass(frozen=True, slots=True)
class Hunk:
    id: int
    start: int  # in the note's text
    end: int
    old: str
    new: str
    reason: str = ""  # why the AI makes it ("update the count in the intro")
    issues: tuple[Issue, ...] = ()
    outside: bool = False  # not in the text the user selected


@dataclass(frozen=True, slots=True)
class Region:
    start: int  # in the note
    old: str  # its text now (accepted hunks included)
    hunks: tuple[Hunk, ...]

    @property
    def end(self) -> int:
        return self.start + len(self.old)


@dataclass(frozen=True, slots=True)
class Proposal:
    id: int
    path: str
    regions: tuple[Region, ...]
    notes: tuple[Issue, ...] = field(default=())  # for the bar: already there, maybe update…

    @property
    def hunks(self) -> tuple[Hunk, ...]:
        return tuple(h for r in self.regions for h in r.hunks)


@dataclass(frozen=True, slots=True)
class Change:
    start: int
    end: int
    insert: str


@dataclass(frozen=True, slots=True)
class Edit:
    """One change to propose: ``text[start:end]`` becomes ``new``."""

    start: int
    end: int
    new: str
    reason: str = ""
    issues: tuple[Issue, ...] = ()
    outside: bool = False


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _hunks(start: int, old: str, new: str, edits: Sequence[Edit] = ()) -> tuple[Hunk, ...]:
    """Line hunks turning ``old`` (at ``start``) into ``new``; each takes the reason, issues and
    ``outside`` of the first of ``edits`` it overlaps."""
    if old.endswith("\n") and not new.endswith("\n"):
        new += "\n"  # keep the region's line break: the diff is about the lines
    a, b = _lines(old), _lines(new)
    offsets = [0, *itertools.accumulate(len(line) for line in a)]
    out: list[Hunk] = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        h_start, h_end = start + offsets[i1], start + offsets[i2]
        source = next(
            (e for e in edits if e.start <= h_end and h_start <= e.end), edits[0] if edits else None
        )
        out.append(
            Hunk(
                next(_ids),
                h_start,
                h_end,
                "".join(a[i1:i2]),
                "".join(b[j1:j2]),
                source.reason if source else "",
                source.issues if source else (),
                source.outside if source else False,
            )
        )
    return tuple(out)


def propose(path: str, text: str, start: int, end: int, new: str) -> Proposal | None:
    """A proposal to replace ``text[start:end]`` by ``new`` (None when nothing changes)."""
    old = text[start:end]
    hunks = _hunks(start, old, new) if old != new else ()
    if not hunks:
        return None
    return Proposal(next(_ids), path, (Region(start, old, hunks),))


def _line_span(text: str, start: int, end: int) -> tuple[int, int]:
    """``start``–``end`` widened to whole lines (with the last line's break)."""
    a = text.rfind("\n", 0, start) + 1
    b = text.find("\n", max(start, end - 1) if end > start else end)
    return a, len(text) if b < 0 else b + 1


def propose_many(
    path: str, text: str, edits: Sequence[Edit], notes: Sequence[Issue] = ()
) -> Proposal | None:
    """One proposal for several changes of ``text`` (they do not overlap): a region of whole
    lines around each, regions that touch merged. None when nothing changes."""
    spans: list[tuple[int, int, list[Edit]]] = []
    for e in sorted(edits, key=lambda e: (e.start, e.end)):
        a, b = _line_span(text, e.start, e.end)
        if spans and a <= spans[-1][1]:
            pa, pb, group = spans[-1]
            spans[-1] = (pa, max(pb, b), [*group, e])
        else:
            spans.append((a, b, [e]))
    regions: list[Region] = []
    for a, b, group in spans:
        old = text[a:b]
        new = old
        for e in sorted(group, key=lambda e: e.start, reverse=True):
            new = new[: e.start - a] + e.new + new[e.end - a :]
        hunks = _hunks(a, old, new, group) if new != old else ()
        if hunks:
            regions.append(Region(a, old, hunks))
    if not regions:
        return None
    return Proposal(next(_ids), path, tuple(regions), tuple(notes))


def _locate_region(region: Region, text: str) -> Region | None:
    if text[region.start : region.end] == region.old:
        return region
    first = text.find(region.old)
    if not region.old or first < 0 or text.find(region.old, first + 1) >= 0:
        return None
    delta = first - region.start
    moved = tuple(replace(h, start=h.start + delta, end=h.end + delta) for h in region.hunks)
    return replace(region, start=first, hunks=moved)


def locate(proposal: Proposal, text: str) -> Proposal | None:
    """``proposal`` moved to where its regions are in ``text`` now; None when any is out of
    date (see :func:`stale_hunks` for which)."""
    regions = [_locate_region(r, text) for r in proposal.regions]
    if any(r is None for r in regions):
        return None
    return replace(proposal, regions=tuple(r for r in regions if r is not None))


def stale_hunks(proposal: Proposal, text: str) -> set[int]:
    """Ids of the hunks whose region is out of date in ``text``."""
    return {h.id for r in proposal.regions if _locate_region(r, text) is None for h in r.hunks}


def accept(
    proposal: Proposal, text: str, hunk_ids: set[int] | None = None
) -> tuple[list[Change], Proposal | None] | None:
    """Apply the hunks ``hunk_ids`` (all when None) to ``text``: the changes to make and what is
    left of the proposal (None when nothing is). Hunks of an out-of-date region are not applied
    and are dropped from what is left. None when none of the wanted hunks can be applied."""
    wanted = [h for h in proposal.hunks if hunk_ids is None or h.id in hunk_ids]
    changes: list[Change] = []
    kept: list[Region] = []
    for region in proposal.regions:
        here = _locate_region(region, text)
        if here is None:
            continue  # out of date: neither applied nor kept
        take = [h for h in here.hunks if h.id in {w.id for w in wanted}]
        changes.extend(Change(h.start, h.end, h.new) for h in take)
        rest: list[Hunk] = []
        shift = 0
        old = here.old
        for h in here.hunks:
            if h in take:
                at = h.start - here.start + shift
                old = old[:at] + h.new + old[at + len(h.old) :]
                shift += len(h.new) - len(h.old)
            else:
                rest.append(replace(h, start=h.start + shift, end=h.end + shift))
        if rest:
            kept.append(replace(here, old=old, hunks=tuple(rest)))
    if wanted and not changes:
        return None
    # regions after an applied change move by what it added or removed
    moved: list[Region] = []
    for region in kept:
        delta = sum(len(c.insert) - (c.end - c.start) for c in changes if c.end <= region.start)
        hunks = tuple(replace(h, start=h.start + delta, end=h.end + delta) for h in region.hunks)
        moved.append(replace(region, start=region.start + delta, hunks=hunks))
    left = replace(proposal, regions=tuple(moved)) if moved else None
    return changes, left


def reject(proposal: Proposal, hunk_id: int | None = None) -> Proposal | None:
    """Drop one hunk (or all when None); None when nothing is left."""
    if hunk_id is None:
        return None
    regions = []
    for r in proposal.regions:
        rest = tuple(h for h in r.hunks if h.id != hunk_id)
        if rest:
            regions.append(replace(r, hunks=rest))
    return replace(proposal, regions=tuple(regions)) if regions else None


def apply_changes(text: str, changes: list[Change]) -> str:
    """``text`` with ``changes`` made (they do not overlap)."""
    for c in sorted(changes, key=lambda c: c.start, reverse=True):
        text = text[: c.start] + c.insert + text[c.end :]
    return text


def word_marks(old: str, new: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]] | None:
    """The words that differ between ``old`` and ``new`` (code-point ranges in each), for marking
    them inside the diff's lines; None when most words changed (marks would be noise)."""
    a, b = _TOKEN.findall(old), _TOKEN.findall(new)
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    words = [t for t in a if t.strip()] or [""]
    same = sum(
        1
        for tag, i1, i2, _, _ in matcher.get_opcodes()
        if tag == "equal"
        for t in a[i1:i2]
        if t.strip()
    )
    if 1 - same / len(words) > WORD_MARK_LIMIT:
        return None
    pos_a = [0, *itertools.accumulate(len(t) for t in a)]
    pos_b = [0, *itertools.accumulate(len(t) for t in b)]
    gone: list[tuple[int, int]] = []
    came: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1 and "".join(a[i1:i2]).strip():
            gone.append((pos_a[i1], pos_a[i2]))
        if j2 > j1 and "".join(b[j1:j2]).strip():
            came.append((pos_b[j1], pos_b[j2]))
    return gone, came
