"""Finding the notes one step is about (PLAN_vault_agent §4, P30.16–P30.19): candidates →
judge → a second round from the kept notes → one result set, inside the step's budget.

A step with a fixed note set (a folder, a tag, named notes, the last result) and no topic to
search for takes those notes as they are — no judging, they are what the user named. A step
with search terms is searched (inside its scope when it has one) and judged. No UI imports.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.vault.candidates import Candidates, Gatherer
from paper_pile.core.ai.vault.expand import more_terms
from paper_pile.core.ai.vault.judge import Facts, Judged, judge, to_results
from paper_pile.core.ai.vault.plan import Choice, PlannedStep
from paper_pile.core.ai.vault.results import ResultItem, ResultSet

Progress = Callable[[str, int, int], None]  # stage, done, total


@dataclass(frozen=True, slots=True)
class Budgets:
    """How far one step may go (PLAN_vault_agent §4 step 4; defaults to confirm after the
    baseline, §11). Above ``candidates`` the user is asked before judging."""

    candidates: int = 60
    second_round: bool = True
    second_candidates: int = 20


DEFAULT_BUDGETS = Budgets()


@dataclass(slots=True)
class Found:
    results: ResultSet
    judged: list[Judged] = field(default_factory=list)
    total: int = 0  # candidates found before the cap
    capped: bool = False  # more matched than the budget allows: the caller may ask
    terms: list[str] = field(default_factory=list)  # every term searched
    rounds: int = 0


def _fixed(request: str, cands: Candidates) -> Found:
    items = [ResultItem(c.path, c.title, "", "yes", c.heading) for c in cands.items]
    return Found(ResultSet(request, items), total=cands.total, capped=cands.capped)


async def find_notes(
    engine: AiEngine,
    gatherer: Gatherer,
    request: str,
    planned: PlannedStep,
    facts: Facts,
    *,
    budgets: Budgets = DEFAULT_BUDGETS,
    on_progress: Progress | None = None,
    paths: Sequence[str] | None = None,
) -> Found:
    """The notes ``planned`` is about. ``paths`` overrides the step's own notes (a step that
    works on what an earlier step found). ``request`` is what the judge reads (the step's
    detail, else the user's message)."""

    def progress(stage: str, done: int, total: int) -> None:
        if on_progress is not None:
            on_progress(stage, done, total)

    step = planned.step
    notes = list(paths) if paths is not None else planned.paths
    if not (planned.search and step.terms):
        every = notes if notes is not None else [r.path for r in gatherer.tools.resolver.readable()]
        return _fixed(request, gatherer.from_paths(every, budgets.candidates))

    terms = list(step.terms)
    progress("search", 0, 1)
    first = gatherer.gather(terms, notes, budgets.candidates)
    progress("search", 1, 1)
    found = Found(ResultSet(request), total=first.total, capped=first.capped, terms=terms)
    if not first.items:
        return found
    found.judged = await judge(
        engine,
        request,
        first.items,
        facts,
        on_batch=lambda d, t: progress("judge", d, t),
    )
    found.rounds = 1
    if budgets.second_round:
        extra = await more_terms(engine, step.topic or request, found.judged, terms)
        if extra:
            seen = {j.candidate.path for j in found.judged}
            again = gatherer.gather(extra, notes, budgets.candidates + budgets.second_candidates)
            new = [c for c in again.items if c.path not in seen][: budgets.second_candidates]
            found.terms += extra
            if new:
                found.judged += await judge(
                    engine,
                    request,
                    new,
                    facts,
                    on_batch=lambda d, t: progress("judge more", d, t),
                )
                found.rounds = 2
    found.results = to_results(request, found.judged)
    return found


def big_job(found: Found, budgets: Budgets = DEFAULT_BUDGETS) -> Choice | None:
    """The question to ask when more notes matched than the budget allows (PLAN_vault_agent
    §4 step 4): judge the best ones, or narrow the request first. None when within budget."""
    if not found.capped:
        return None
    best = f"Use the best {budgets.candidates}"
    return Choice(
        f"{found.total} notes match. Use the best {budgets.candidates}, or narrow it down "
        "(a folder, a tag, a period)?",
        (best, "Narrow it down"),
        ("best", "narrow"),
        "budget",
    )
