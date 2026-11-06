"""Next-step hints from what a step found (PLAN_vault_agent §3.5, P30.24) — made from data
(folders, tags, the judge's maybes, the action), never from a model call, and never naming a
note that does not exist or that the AI may not read. No UI imports.
"""

import difflib
from collections import Counter
from collections.abc import Sequence

from paper_pile.core.ai.vault.plan import PlannedStep
from paper_pile.core.ai.vault.reply import Hint
from paper_pile.core.ai.vault.results import ResultSet
from paper_pile.core.ai.vault.scope import ScopeResolver, note_folders

MAX_NEAR = 3
NEAR_CUTOFF = 0.6


def _folder(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def near_names(words: Sequence[str], names: Sequence[str]) -> list[str]:
    """Names (tags, folders) close to any of ``words``: containing one, or spelt like one."""
    out: list[str] = []
    low = {n.casefold(): n for n in names}
    for word in words:
        w = word.casefold().strip()
        if len(w) < 3:
            continue
        found = [orig for key, orig in low.items() if w in key or key in w]
        found += [low[k] for k in difflib.get_close_matches(w, list(low), n=2, cutoff=NEAR_CUTOFF)]
        for name in found:
            if name not in out:
                out.append(name)
    return out[:MAX_NEAR]


def hints(
    planned: PlannedStep,
    results: ResultSet,
    resolver: ScopeResolver,
    tags: Sequence[str] = (),
) -> list[Hint]:
    """Chips to offer after a step: the unsure notes, a wider or narrower scope, the nearest
    real tags / folders when nothing was found, and the obvious next actions."""
    step = planned.step
    sure, maybe = results.sure(), results.maybe()
    out: list[Hint] = []
    if maybe:
        n = len(maybe)
        out.append(Hint(f"{n} more might be related", "maybe", "maybe"))
    if not sure:
        if planned.paths is not None:
            out.append(Hint("Search the whole vault", "scope", ""))
        words = [w for t in (step.topic, *step.terms) for w in t.split()]
        folders = note_folders(r.path for r in resolver.readable())
        for tag in near_names(words, list(tags)):
            out.append(Hint(f"#{tag}", "near", f"#{tag}"))
        for folder in near_names(words, folders):
            out.append(Hint(f"Folder {folder}", "near", folder))
        return out
    spread = Counter(_folder(i.path) for i in sure)
    if len(spread) > 1 and len(sure) >= 4:
        top, count = spread.most_common(1)[0]
        if top and count < len(sure):
            out.append(Hint(f"Only {top} ({count})", "scope", top))
    if len(sure) >= 2:
        if step.action != "summarise":
            out.append(Hint("Summarise all", "action", "summarise"))
        if step.action != "extract":
            out.append(Hint("Make a table", "action", "extract"))
        out.append(Hint("Open all", "action", "open"))
    return out
