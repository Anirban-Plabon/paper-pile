"""Running a plan on the fast path (PLAN_vault_agent §5.2): each step finds its notes
(``find.py``) and acts on them — locate, answer, summarise, extract, meta — in order; a step
that depends on an earlier one works on that step's notes. Actions that are not built yet
(compare, write, edit, other — M5 / M6) answer so, plainly. A big job stops the run with a
question. No UI imports.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.vault.answer import answer
from paper_pile.core.ai.vault.candidates import Gatherer
from paper_pile.core.ai.vault.cards import CardMaker
from paper_pile.core.ai.vault.extract import extract
from paper_pile.core.ai.vault.find import DEFAULT_BUDGETS, Budgets, big_job, find_notes
from paper_pile.core.ai.vault.hints import hints
from paper_pile.core.ai.vault.meta import MetaResult, VaultMeta
from paper_pile.core.ai.vault.plan import Choice, Plan, PlannedStep
from paper_pile.core.ai.vault.reply import Reply, locate
from paper_pile.core.ai.vault.results import ResultSet
from paper_pile.core.ai.vault.summarise import summarise_many, summarise_note
from paper_pile.core.ai.vault.tools import VaultTools

Progress = Callable[[int, str, int, int], None]  # step, stage, done, total
NOT_YET = {
    "compare": "Comparing notes is not available yet.",
    "write": "Writing a new note from the results is not available yet.",
    "edit": "Changing notes across the vault is not available yet.",
    "other": "I can't do that across the vault yet.",
}


@dataclass(slots=True)
class VaultAgent:
    engine: AiEngine
    tools: VaultTools
    gatherer: Gatherer
    maker: CardMaker
    meta: VaultMeta
    budgets: Budgets = DEFAULT_BUDGETS
    today: Callable[[], date] = date.today

    def facts(self, path: str) -> tuple[list[str], list[str]]:
        ix = self.tools.index
        return ix.tags_of(path), [h.text for h in ix.headings_of(path)]

    def tags(self) -> list[str]:
        readable = {r.path for r in self.tools.resolver.readable()}
        return sorted({t for p, t in self.tools.index.tag_pairs() if p in readable})


@dataclass(slots=True)
class RunResult:
    replies: list[Reply] = field(default_factory=list)
    last: ResultSet | None = None  # the result set follow-ups refer to
    choice: Choice | None = None  # the run stopped to ask this


def meta_text(result: MetaResult) -> str:
    if result.query == "count":
        notes, words = result.rows[0]
        return f"{notes} notes ({words} words)."
    head = f"{result.total} in all" + (
        f", the first {len(result.rows)}:" if len(result.rows) < result.total else ":"
    )
    lines = ["| " + " | ".join(result.columns) + " |", "|" + "---|" * len(result.columns)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in result.rows]
    return head + "\n\n" + "\n".join(lines) if result.rows else f"None ({result.query})."


async def _act(
    agent: VaultAgent,
    planned: PlannedStep,
    request: str,
    results: ResultSet,
    on_text: Callable[[str], None] | None,
    progress: Callable[[str, int, int], None],
) -> Reply:
    step = planned.step
    words = [w for t in step.terms for w in t.split()]
    if step.action in NOT_YET:
        return Reply(NOT_YET[step.action], results)
    if not len(results):
        return Reply("No notes found.", results)
    if step.action == "locate":
        return locate(results)
    if step.action == "answer":
        return await answer(agent.engine, agent.tools, request, results, words, on_text=on_text)
    if step.action == "summarise":
        items = results.sure() or results.maybe()
        if len(items) == 1:
            return await summarise_note(agent.engine, agent.tools, items[0].path, request, results)
        return await summarise_many(
            agent.engine, agent.maker, request, results, on_progress=progress
        )
    if step.action == "extract":
        return await extract(agent.engine, agent.tools, request, results, on_progress=progress)
    return Reply(NOT_YET.get(step.action, NOT_YET["other"]), results)


def _text_for(
    on_text: Callable[[int, str], None] | None, step: int
) -> Callable[[str], None] | None:
    if on_text is None:
        return None
    report = on_text

    def text(t: str) -> None:
        report(step, t)

    return text


async def run_plan(
    agent: VaultAgent,
    plan: Plan,
    message: str,
    *,
    on_progress: Progress | None = None,
    on_text: Callable[[int, str], None] | None = None,
    use_best: bool = False,
) -> RunResult:
    """Every step of a ready ``plan``. ``use_best``: the user already chose to go on with the
    best candidates when a step found more than the budget."""
    out = RunResult()
    found_by_step: list[ResultSet] = []
    for i, planned in enumerate(plan.steps):
        step = planned.step

        def progress(stage: str, done: int, total: int, i: int = i) -> None:
            if on_progress is not None:
                on_progress(i, stage, done, total)

        request = step.detail or message
        if step.action == "meta":
            paths: Sequence[str] | None = planned.paths
            scope = step.scope if paths is not None else None
            result = agent.meta.run(step.meta or "count", scope, days=step.scope.dates)
            out.replies.append(Reply(meta_text(result)))
            found_by_step.append(ResultSet(request))
            continue
        after = (
            found_by_step[planned.after].paths if 0 <= planned.after < len(found_by_step) else None
        )
        found = await find_notes(
            agent.engine,
            agent.gatherer,
            request,
            planned,
            agent.facts,
            budgets=agent.budgets,
            on_progress=progress,
            paths=after,
        )
        ask = None if use_best else big_job(found, agent.budgets)
        if ask is not None:
            out.choice = Choice(ask.question, ask.options, ask.values, ask.kind, step=i)
            return out
        reply = await _act(
            agent,
            planned,
            request,
            found.results,
            _text_for(on_text, i),
            progress,
        )
        reply.hints = hints(planned, found.results, agent.tools.resolver, agent.tags())
        reply.notices = [*plan.notices, *reply.notices] if i == 0 else reply.notices
        out.replies.append(reply)
        found_by_step.append(found.results)
        if len(found.results):
            out.last = found.results
    return out
