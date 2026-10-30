"""The checks of a case (``docs/AI_EDITS.md`` §10), shared by the unit tests and the real run.
Each ``expect`` entry is ``[name, *args]``; every case also gets the safety check: a change with
a warning is never "clean" (it would be applied unseen in *Apply at once*)."""

import difflib
import re
from collections.abc import Callable

from paper_pile.core.ai.guards import change_share, main_script
from paper_pile.core.ai.protect import missing_tokens
from paper_pile.core.parser import headings

from .cases import Outcome

Result = tuple[str, bool, str]  # (check, passed, detail)


def _heads(text: str) -> list[tuple[int, str]]:
    return [(h.level, h.text) for h in headings(text)]


def _changed_lines(before: str, after: str) -> list[str]:
    diff = difflib.ndiff(before.splitlines(), after.splitlines())
    return [line[2:] for line in diff if line[:1] in "+-" and line[2:].strip()]


def _fences(text: str) -> list[str]:
    return re.findall(r"^```[^\n]*\n.*?^```", text, flags=re.MULTILINE | re.DOTALL)


def headings_unchanged(o: Outcome) -> tuple[bool, str]:
    return _heads(o.case.note) == _heads(o.after), str(_heads(o.after))


def new_headings(o: Outcome, levels: list[int]) -> tuple[bool, str]:
    """The headings added are exactly ``levels`` (and none removed)."""
    before, after = _heads(o.case.note), _heads(o.after)
    added = list(after)
    for h in before:
        if h not in added:
            return False, f"lost {h}"
        added.remove(h)
    return sorted(h[0] for h in added) == sorted(levels), str(added)


def new_heading_next_to(o: Outcome, name: str) -> tuple[bool, str]:
    """A new heading sits right before or after the section ``name`` (a section boundary)."""
    before = _heads(o.case.note)
    after = _heads(o.after)
    for i, h in enumerate(after):
        if h not in before:
            near = [after[j][1] for j in (i - 1, i + 1) if 0 <= j < len(after)]
            return name in near, f"{h} between {near}"
    return False, "no new heading"


def contains(o: Outcome, text: str) -> tuple[bool, str]:
    return text in o.after, ""


def not_contains(o: Outcome, text: str) -> tuple[bool, str]:
    return text not in o.after, ""


def change_share_max(o: Outcome, limit: float) -> tuple[bool, str]:
    share = change_share(o.case.note, o.after)
    return share <= limit, f"{share:.2f}"


def changed(o: Outcome) -> tuple[bool, str]:
    return o.after != o.case.note, ""


def unchanged(o: Outcome) -> tuple[bool, str]:
    return o.after == o.case.note, ""


def tokens_kept(o: Outcome) -> tuple[bool, str]:
    lost = missing_tokens(o.case.note, o.after)
    return not lost, f"lost {lost}"


def fences_identical(o: Outcome) -> tuple[bool, str]:
    lost = [f for f in _fences(o.case.note) if f not in o.after]
    return not lost, f"changed {lost}"


def changed_lines_match(o: Outcome, pattern: str) -> tuple[bool, str]:
    lines = _changed_lines(o.case.note, o.after)
    bad = [line for line in lines if not re.search(pattern, line)]
    return bool(lines) and not bad, f"other lines: {bad}" if bad else "nothing changed"


def count_delta(o: Outcome, pattern: str, delta: int) -> tuple[bool, str]:
    rx = re.compile(pattern, re.MULTILINE)
    got = len(rx.findall(o.after)) - len(rx.findall(o.case.note))
    return got == delta, f"{got:+d}"


def table_columns_same(o: Outcome) -> tuple[bool, str]:
    rows = [line for line in o.after.splitlines() if line.lstrip().startswith("|")]
    cols = {line.strip().strip("|").count("|") for line in rows}
    return len(cols) <= 1, f"columns {sorted(cols)}"


def regions_min(o: Outcome, n: int) -> tuple[bool, str]:
    got = len(o.result.proposal.regions) if o.result and o.result.proposal else 0
    return got >= n, str(got)


def note_kind(o: Outcome, kind: str) -> tuple[bool, str]:
    """A note of ``kind`` came with the result — on the proposal or on one of its changes
    (``exists``: also "already in the note")."""
    if o.result is None:
        return False, "no result"
    proposal = o.result.proposal
    kinds = [i.kind for i in proposal.notes] if proposal else []
    kinds += [i.kind for c in o.result.changes for i in c.issues]  # "May repeat …" on a change
    if kind == "exists" and o.result.already:
        kinds.append("exists")
    return kind in kinds, str(kinds)


def inserted_after(o: Outcome, anchor: str) -> tuple[bool, str]:
    """The answer starts right after ``anchor`` (a blank line between, a block of its own)."""
    at = o.after.find(anchor)
    tail = o.after[at + len(anchor) :] if at >= 0 else ""
    first = o.answer.strip().split("\n", 1)[0]
    return bool(first) and tail.startswith("\n\n" + first), repr(tail[:60])


def answer_not_contains(o: Outcome, text: str) -> tuple[bool, str]:
    return text not in o.answer, repr(o.answer[:80])


def script_kept(o: Outcome) -> tuple[bool, str]:
    a, b = main_script(o.case.note), main_script(o.after)
    return a == b, f"{a} → {b}"


def no_error(o: Outcome) -> tuple[bool, str]:
    problem = o.error or (o.result.error if o.result else "")
    return not problem, problem


CHECKS: dict[str, Callable[..., tuple[bool, str]]] = {
    f.__name__: f
    for f in (
        headings_unchanged,
        new_headings,
        new_heading_next_to,
        contains,
        not_contains,
        change_share_max,
        changed,
        unchanged,
        tokens_kept,
        fences_identical,
        changed_lines_match,
        count_delta,
        table_columns_same,
        regions_min,
        note_kind,
        inserted_after,
        answer_not_contains,
        script_kept,
        no_error,
    )
}


def safe(o: Outcome) -> tuple[bool, str]:
    """Nothing that broke a guard would be applied unseen."""
    if o.result is None or not o.result.changes:
        return True, ""
    warned = any(i.severity == "warn" for c in o.result.changes for i in c.issues)
    return not (warned and o.result.clean), "a warning but clean"


def run_checks(o: Outcome, *, unit: bool = False) -> list[Result]:
    """The case's checks (``unit``: also those of the scripted replies' wording)."""
    out: list[Result] = []
    wording = o.case.expect_unit if unit else []
    for name, *args in [["no_error"], *o.case.expect, *wording]:
        ok, detail = CHECKS[name](o, *args)
        label = name + (f"({', '.join(map(repr, args))})" if args else "")
        out.append((label, ok, detail))
    ok, detail = safe(o)
    out.append(("safe", ok, detail))
    return out
