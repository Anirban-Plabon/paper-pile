"""Running a plan (PLAN_vault_agent §5.2): each step, in order, either takes the fast path —
find its notes (``find.py``) and act on them: locate, answer, summarise, extract, meta — or,
for ``compare`` and open-ended steps, the agent loop (``loop.py``). A step that depends on an
earlier one works on that step's notes. ``edit`` / ``write`` end in a review (M6): proposals
only, the run stops until the user picks what to apply. A big job stops the run with a
question; Stop ends it between steps (and inside the loop between actions). No UI imports.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.vault.answer import answer
from paper_pile.core.ai.vault.candidates import Gatherer
from paper_pile.core.ai.vault.cards import CardMaker
from paper_pile.core.ai.vault.edits import NoteWriter, VaultWriter, propose_batch, review_text
from paper_pile.core.ai.vault.extract import extract
from paper_pile.core.ai.vault.find import DEFAULT_BUDGETS, Budgets, big_job, find_notes
from paper_pile.core.ai.vault.hints import hints
from paper_pile.core.ai.vault.loop import AgentLoop
from paper_pile.core.ai.vault.meta import MetaResult, VaultMeta
from paper_pile.core.ai.vault.newnote import propose_new_note
from paper_pile.core.ai.vault.plan import Choice, Plan, PlannedStep
from paper_pile.core.ai.vault.reply import Reply, locate
from paper_pile.core.ai.vault.results import ResultSet
from paper_pile.core.ai.vault.scope import note_folders
from paper_pile.core.ai.vault.summarise import summarise_many, summarise_note
from paper_pile.core.ai.vault.tools import VaultTools
from paper_pile.core.ai.vault.understand import Step

Progress = Callable[[int, str, int, int], None]  # step, stage, done, total
LOOP_ACTIONS = {"compare", "other"}  # no fixed pipeline: the agent loop (§5.2)
CHANGE_ACTIONS = {"edit", "write"}  # end in a review: nothing is written before the user picks


@dataclass(slots=True)
class VaultAgent:
    engine: AiEngine
    tools: VaultTools
    gatherer: Gatherer
    maker: CardMaker
    meta: VaultMeta
    budgets: Budgets = DEFAULT_BUDGETS
    today: Callable[[], date] = date.today
    memory: str = ""  # the vault memory file (memory.py)
    writer: NoteWriter | None = None  # how notes are read / written for edits (M6)
    link: Callable[[str], str] = lambda p: p.rsplit("/", 1)[-1][:-3]  # path → [[link]] name

    def facts(self, path: str) -> tuple[list[str], list[str]]:
        ix = self.tools.index
        return ix.tags_of(path), [h.text for h in ix.headings_of(path)]

    def tags(self) -> list[str]:
        readable = {r.path for r in self.tools.resolver.readable()}
        return sorted({t for p, t in self.tools.index.tag_pairs() if p in readable})

    def folders(self) -> list[str]:
        return note_folders(r.path for r in self.tools.resolver.readable())

    def loop(self) -> AgentLoop:
        return AgentLoop(self.engine, self.tools, self.meta, today=self.today, memory=self.memory)


@dataclass(slots=True)
class RunResult:
    replies: list[Reply] = field(default_factory=list)
    last: ResultSet | None = None  # the result set follow-ups refer to
    choice: Choice | None = None  # the run stopped to ask this
    stopped: bool = False


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
    if not len(results):
        return Reply("No notes found.", results)
    if step.action in CHANGE_ACTIONS:
        return await _change(agent, step, request, results, progress)
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
    return Reply("I can't do that across the vault yet.", results)


async def _change(
    agent: VaultAgent,
    step: Step,
    request: str,
    results: ResultSet,
    progress: Callable[[str, int, int], None],
) -> Reply:
    """Edits across notes / a new note: proposals for review — nothing is written here."""
    writer = agent.writer or VaultWriter(agent.engine.vault)
    if step.action == "write":
        folder = step.scope.folders[0] if step.scope.folders else ""
        batch = await propose_new_note(
            agent.engine,
            agent.tools,
            agent.maker,
            request,
            results,
            topic=step.topic,
            folder=folder,
            link=agent.link,
        )
    else:
        items = results.sure() or results.maybe()
        batch = await propose_batch(
            agent.engine,
            request,
            [(i.path, i.title) for i in items],
            writer,
            on_progress=progress,
        )
    return Reply(review_text(batch), results, review=batch)


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
    stop: Callable[[], bool] = lambda: False,
    skip: frozenset[str] = frozenset(),
) -> RunResult:
    """Every step of a ready ``plan``. ``use_best``: the user already chose to go on with the
    best candidates when a step found more than the budget."""
    out = RunResult()
    found_by_step: list[ResultSet] = []
    for i, planned in enumerate(plan.steps):
        if stop():
            out.stopped = True
            break
        step = planned.step

        def progress(stage: str, done: int, total: int, i: int = i) -> None:
            if on_progress is not None:
                on_progress(i, stage, done, total)

        def loop_step(k: int, label: str, i: int = i) -> None:
            if on_progress is not None:
                on_progress(i, f"loop: {label}", k + 1, 0)

        request = step.detail or message
        if step.action in LOOP_ACTIONS:
            reply = await agent.loop().run(
                request,
                agent.folders(),
                on_step=loop_step,
                on_text=_text_for(on_text, i),
                stop=stop,
            )
            out.replies.append(reply)
            found_by_step.append(reply.results)
            if len(reply.results):
                out.last = reply.results
            continue
        if step.action == "meta":
            paths: Sequence[str] | None = planned.paths
            scope = step.scope if paths is not None else None
            result = agent.meta.run(step.meta or "count", scope, days=step.scope.dates)
            out.replies.append(Reply(meta_text(result)))
            found_by_step.append(ResultSet(request))
            continue
        after = None
        if 0 <= planned.after < len(found_by_step):  # an earlier step's notes: its sure ones
            earlier = found_by_step[planned.after]  # (a maybe must not become sure here)
            after = [i.path for i in earlier.sure()] or earlier.paths
        # a change's instruction is not what notes are judged by: its topic is
        judged_by = step.topic if step.action in CHANGE_ACTIONS and step.topic else request
        found = await find_notes(
            agent.engine,
            agent.gatherer,
            judged_by,
            planned,
            agent.facts,
            budgets=agent.budgets,
            on_progress=progress,
            paths=after,
        )
        if skip:  # the note the request came from is not its own answer
            found.results = found.results.narrowed(lambda i: i.path not in skip)
        ask = None if use_best else big_job(found, agent.budgets)
        if ask is not None:
            out.choice = Choice(ask.question, ask.options, ask.values, ask.kind, step=i)
            return out
        reply = await _act(agent, planned, request, found.results, _text_for(on_text, i), progress)
        reply.hints = hints(planned, found.results, agent.tools.resolver, agent.tags())
        reply.notices = [*plan.notices, *reply.notices] if i == 0 else reply.notices
        out.replies.append(reply)
        found_by_step.append(found.results)
        if len(found.results):
            out.last = found.results
        if reply.review is not None and reply.review.ready:
            if i + 1 < len(plan.steps):
                reply.notices.append("The steps after this one wait until the change is done.")
            break  # the user reviews before anything else happens
    return out
