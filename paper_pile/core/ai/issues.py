"""What the checks of an AI edit found (PLAN §4.29, ``docs/AI_EDITS.md`` §4.6): shown on the
change it belongs to. ``fixed``: repaired (a grey note); ``warn``: shown, Accept still works, and
the edit is never applied unseen; ``retry``: ask the model once more; ``drop``: that change is
not shown and the bar says so. No UI imports.
"""

from dataclasses import dataclass
from typing import Literal

Severity = Literal["fixed", "warn", "retry", "drop"]


@dataclass(frozen=True, slots=True)
class Issue:
    kind: str  # "heading", "tokens", "size", "exists", "elsewhere", "maybe-update", …
    severity: Severity
    message: str  # for the user
    feedback: str = ""  # for the model, on a retry
    data: str = ""  # e.g. the block id or path it points at


def worst(issues: list[Issue]) -> Severity | None:
    order: tuple[Severity, ...] = ("drop", "retry", "warn", "fixed")
    found = {i.severity for i in issues}
    return next((s for s in order if s in found), None)
