"""One AI change of a note, from the request to a proposal (PLAN §4.29, ``docs/AI_EDITS.md`` §4).

The model decides *what* to change and *where*; Python decides *how* it goes in and whether it
is safe:

0. the target (selection, or the note's body) and the intent (may it touch other places?);
1. a plan, as JSON naming only real blocks — skipped when only the target changes (one call);
2. one plain-text call per planned change, each seeing what the earlier ones wrote;
3. cleaning and checks (``cleanup``, ``guards``), one retry with feedback when a check fails;
4. already-there checks in the note and the vault; 5. "maybe also update" suggestions;
6. one proposal with a region per place.

Progress goes to ``on_progress``; Stop (cancelling the task) or a failure keeps what was
finished — :meth:`EditRun.result` builds the proposal from it. No UI imports.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from paper_pile.core.ai.blocks import Block, block_map
from paper_pile.core.ai.cleanup import clean_reply
from paper_pile.core.ai.consistency import Suggestion, suggestions
from paper_pile.core.ai.context import estimate_tokens
from paper_pile.core.ai.edit_context import EditBudget, note_view, vault_view
from paper_pile.core.ai.edits import FINISHED, EditTooLongError, reply_room
from paper_pile.core.ai.engine import AiEngine, message_tokens
from paper_pile.core.ai.existing import in_note, in_vault
from paper_pile.core.ai.guards import GuardContext, check
from paper_pile.core.ai.intent import Intent, edit_intent
from paper_pile.core.ai.issues import Issue
from paper_pile.core.ai.plan import (
    Plan,
    PlannedEdit,
    fallback_plan,
    parse_plan,
    plan_schema,
    plan_task,
    snap,
)
from paper_pile.core.ai.proposals import Edit, Proposal, propose_many
from paper_pile.core.ai.provider import ChatMessage, ProviderError
from paper_pile.core.ai.write import (
    WRITE_RULES,
    PlannedChange,
    WriteJob,
    delete_change,
    fit_answer,
    write_job,
)
from paper_pile.core.index import query_words

log = logging.getLogger("paper_pile.ai.edit")

ADD_ANSWER = 600  # tokens for new text
ADD_ANSWER_MAX = 1500
WRITE_TEMPERATURE = 0.3  # at most: low temperature keeps the model from changing too much
VAULT_HITS = 3
AGAIN = "Reply with the whole new text again, nothing else."


@dataclass
class EditResult:
    proposal: Proposal | None
    changes: list[PlannedChange]
    question: str = ""  # the model asks before planning anything
    already: str = ""  # everything asked for is already in the note
    error: str = ""  # a failure part-way (what was finished is in the proposal)
    dropped: list[str] = field(default_factory=list)  # changes left out, and why
    suggestions: list[Suggestion] = field(default_factory=list)
    calls: int = 0

    @property
    def clean(self) -> bool:
        """May it be applied at once (*Apply at once*): nothing outside the target, no
        warning (PLAN §4.29, the user's answer 1)."""
        return bool(self.changes) and all(
            not c.outside and all(i.severity in ("fixed", "info") for i in c.issues)
            for c in self.changes
        )


def selection_blocks(
    blocks: Sequence[Block], start: int, end: int
) -> tuple[list[Block], list[str]]:
    """``blocks`` with those the selection only partly covers cut to it (a part of a code block
    is no longer "fixed": it is not whole), and the ids of the blocks it covers."""
    out: list[Block] = []
    ids: list[str] = []
    for b in blocks:
        if b.end <= start or b.start >= end or b.kind == "front_matter":
            out.append(b)
            continue
        cut = replace(b, start=max(b.start, start), end=min(b.end, end))
        if (cut.start, cut.end) != (b.start, b.end):
            cut = replace(cut, fixed=False)
        out.append(cut)
        ids.append(b.id)
    return out, ids


class EditRun:
    def __init__(
        self,
        engine: AiEngine,
        *,
        path: str,
        note: str,
        selection: tuple[int, int] | None,
        instruction: str,
        command_id: str = "ai-rewrite",
        groups: Sequence[str] = (),
        planning: str = "auto",
        translate: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self.engine = engine
        self.path = path
        self.note = note
        self.instruction = instruction.strip()
        self.intent: Intent = edit_intent(command_id, instruction, groups)
        self.planning = planning
        self.translate = translate
        self.on_progress = on_progress or (lambda _s: None)
        all_blocks = block_map(note)
        if selection is not None and note[selection[0] : selection[1]].strip():
            self.blocks, self.targets = selection_blocks(all_blocks, *sorted(selection))
        else:
            self.blocks, self.targets = all_blocks, []
        self.changes: list[PlannedChange] = []
        self.dropped: list[str] = []
        self.notes: list[Issue] = []
        self.calls = 0
        self.error = ""
        self._prefix: list[ChatMessage] = []
        self._vault: list[tuple[str, str, str]] = []
        self._window = 0
        self._changing: list[str] = []

    # ---- the run ---------------------------------------------------------------------------

    async def run(self) -> EditResult:
        self.engine.require_note(self.path, self.note)
        self._window = await self.engine.window()
        plan = await self._plan()
        if plan.question and not plan.edits:
            return EditResult(None, [], question=plan.question, calls=self.calls)
        if not plan.edits and any(a == "all" for _, a in plan.already):
            return EditResult(None, [], already=self._already_text(plan), calls=self.calls)
        if plan.note:
            self.notes.append(Issue("plan", "info", plan.note))
        await self._write_all(plan)
        return self.result()

    def result(self) -> EditResult:
        """The proposal from what is finished (also after Stop or a failure)."""
        self.on_progress("Checking…")
        found = suggestions(self.blocks, self.note, self.changes) if self.changes else []
        notes = [*self.notes, *self._elsewhere()]
        notes += [Issue("maybe-update", "info", s.why, data=s.block) for s in found]
        proposal = propose_many(
            self.path,
            self.note,
            [Edit(c.start, c.end, c.new, c.why, c.issues, c.outside) for c in self.changes],
            notes,
        )
        return EditResult(
            proposal, list(self.changes), error=self.error, dropped=list(self.dropped),
            suggestions=found, calls=self.calls,
        )  # fmt: skip

    async def update(self, suggestion: Suggestion) -> EditResult:
        """ "Maybe also update …" → Update: one more change there (the list or table grows by
        what it lacks, or the block is changed)."""
        if not self._window:
            self._window = await self.engine.window()
        grow = suggestion.action == "add_after"
        edit = PlannedEdit(
            suggestion.why, "add_after" if grow else "change", suggestion.block, outside=True
        )
        await self._write_all(Plan((edit,)))
        return self.result()

    # ---- 1. plan ---------------------------------------------------------------------------

    async def _plan(self) -> Plan:
        if self.intent.scope == "text" or self.planning == "selection":
            return self._fast_plan()
        budget = EditBudget.for_window(self._window)
        for attempt in range(2):
            self.on_progress("Planning…")
            prefix = self._view(budget if attempt == 0 else _halved(budget))
            ids = [b.id for b in self.blocks if not b.fixed]
            vids = [f"V{n}" for n in range(1, len(self._vault) + 1)]
            schema = plan_schema(ids, vids)
            ask = [*prefix, ChatMessage("user", plan_task(self.instruction, self.targets, schema))]
            self.calls += 1
            data = await self.engine.ask_json(ask, schema, max_answer=512)
            plan = parse_plan(data, self.blocks, self.targets, vids)
            if plan is not None:
                self._prefix = prefix
                return snap(plan, self.blocks)
            log.info("no usable plan (try %d)", attempt + 1)
        self._prefix = self._view(budget)
        return snap(
            fallback_plan(
                self.blocks, self.note, self.targets, self.instruction, adds=self.intent.adds
            ),
            self.blocks,
        )

    def _fast_plan(self) -> Plan:
        """Only the target changes: one change over it (the whole body when nothing is
        selected)."""
        if self.targets:
            return Plan((PlannedEdit("", "change", self.targets[0], last=self.targets[-1]),))
        body = [b for b in self.blocks if b.kind != "front_matter"]
        if not body:
            return Plan(())
        return Plan((PlannedEdit("", "change", body[0].id, last=body[-1].id),))

    def _view(self, budget: EditBudget) -> list[ChatMessage]:
        """The shared start of the plan and write calls: rules, then the note as blocks (and
        sections of other notes on the same subject)."""
        view = note_view(self.note, self.blocks, self.targets, self.instruction, budget)
        words = " ".join(query_words(self.instruction, most=8))
        self._vault = self.engine.related_sections(words, skip=self.path, limit=VAULT_HITS)
        text = "The note, as numbered blocks:\n" + view.text
        if self._vault:
            text += "\n\nSections of other notes (context only):\n" + vault_view(
                self._vault, budget.vault
            )
        system = self.engine.system_prompt() + "\n\n" + WRITE_RULES
        return [ChatMessage("system", system), ChatMessage("user", text)]

    # ---- 2–3. write and check ----------------------------------------------------------------

    def _order(self, plan: Plan) -> list[PlannedEdit]:
        mine = set(self.targets)
        first = [e for e in plan.edits if e.block in mine and e.action == "change"]
        adds = [e for e in plan.edits if e.action.startswith("add") and e not in first]
        rest = [e for e in plan.edits if e not in first and e not in adds]
        return [*first, *adds, *rest]

    async def _write_all(self, plan: Plan) -> None:
        edits = self._order(plan)
        self._changing = [e.block for e in edits if e.action in ("change", "delete")]
        earlier: list[str] = [c.new.strip() for c in self.changes]
        try:
            for n, edit in enumerate(edits, 1):
                if edit.action == "delete":
                    self.changes.append(delete_change(edit, self.blocks, self.note))
                    continue
                self.on_progress(f"Writing {n} of {len(edits)}…" if len(edits) > 1 else "Writing…")
                change = await self._write_one(edit, earlier)
                if change is not None:
                    self.changes.append(change)
                    earlier.append(change.new.strip())
        except ProviderError as exc:  # what was finished stays
            self.error = str(exc)

    async def _write_one(self, edit: PlannedEdit, earlier: Sequence[str]) -> PlannedChange | None:
        job = write_job(edit, self.blocks, self.note, self.instruction, earlier)
        messages = self._messages(job)
        ctx = self._guard_context(edit, job)
        issues: list[Issue] = []
        change: PlannedChange | None = None
        for attempt in range(2):
            answer, finished = await self._ask(messages, job)
            if not finished or not answer.strip():
                self.dropped.append(_dropped(edit, "the answer was cut off or empty"))
                return None
            cleaned = clean_reply(answer, job.old)
            text, issues = check(ctx, job.masked, cleaned, retried=attempt == 1)
            change = fit_answer(job, self.blocks, self.note, text)
            retry = [i for i in issues if i.severity == "retry"]
            if change is None:
                retry.append(
                    Issue("keep", "retry", "", "Keep every ⟦KEEP n⟧ line exactly, on its own line.")
                )
            if not retry or attempt == 1:
                break
            feedback = " ".join(i.feedback for i in retry if i.feedback)
            messages = [
                *messages,
                ChatMessage("assistant", answer),
                ChatMessage(
                    "user", f"{feedback} Reply with the whole new text again, nothing else."
                ),
            ]
        if change is None:
            self.dropped.append(_dropped(edit, "a code or math block would have been lost"))
            return None
        if edit.action.startswith("add"):  # already in the note? (blocks being changed aside)
            skip = [*self.targets, *self._changing]
            issues = [*issues, *in_note(text, self.blocks, self.note, skip=skip)]
        kept = tuple(i for i in (*change.issues, *issues) if i.severity != "retry")
        return replace(change, issues=kept)

    def _messages(self, job: WriteJob) -> list[ChatMessage]:
        """The shared start + the task when it fits with the answer, else a compact prompt
        (the task carries its own context)."""
        room = self._room(job)
        if self._prefix:
            full = [*self._prefix, ChatMessage("user", job.task)]
            if message_tokens(full) + room <= self._window:
                return full
        system = self.engine.system_prompt() + "\n\n" + WRITE_RULES
        compact = [ChatMessage("system", system), ChatMessage("user", job.task)]
        if message_tokens(compact) + room > self._window:
            raise EditTooLongError(
                "The text is too long for this model to rewrite at once. Select less."
            )
        return compact

    def _room(self, job: WriteJob) -> int:
        if job.old:
            return reply_room(estimate_tokens(job.old))
        return min(ADD_ANSWER, ADD_ANSWER_MAX)

    async def _ask(self, messages: list[ChatMessage], job: WriteJob) -> tuple[str, bool]:
        finish: list[str] = []
        self.calls += 1
        chosen = self.engine.setting("ai.temperature", 0.8)
        temperature = min(
            float(chosen) if isinstance(chosen, int | float) else 0.8, WRITE_TEMPERATURE
        )
        parts = [
            piece
            async for piece in self.engine.stream(
                messages,
                self._window,
                on_finish=finish.append,
                think=False,
                temperature=temperature,
                max_answer=self._room(job),
            )
        ]
        return "".join(parts), finish == [FINISHED]

    def _guard_context(self, edit: PlannedEdit, job: WriteJob) -> GuardContext:
        ids = [b.id for b in self.blocks]
        at = ids.index(edit.block)
        last = ids.index(edit.last) if edit.last in ids else at
        near = []
        if at > 0:
            near.append(self.blocks[at - 1].text(self.note))
        if last + 1 < len(self.blocks):
            near.append(self.blocks[last + 1].text(self.note))
        if edit.action.startswith("add"):
            near.append(self.blocks[at].text(self.note))
        return GuardContext(
            edit.action,
            self.instruction,
            self.intent.size if edit.block in self.targets or not self.targets else "medium",
            edit.new_section,
            edit.level,
            tuple(near),
            self.translate,
            job.keep,
        )

    # ---- 4. already there --------------------------------------------------------------------

    def _elsewhere(self) -> list[Issue]:
        added = "\n\n".join(c.new for c in self.changes if c.start == c.end)
        if not added.strip() or not self._vault:
            return []
        return in_vault(added, self._vault)

    def _already_text(self, plan: Plan) -> str:
        by_id = {b.id: b for b in self.blocks}
        for block_id, amount in plan.already:
            b = by_id.get(block_id)
            if amount == "all" and b is not None:
                words = b.text(self.note).split()
                quote = " ".join(words[:12]) + (" …" if len(words) > 12 else "")
                where = f"{b.path[-1]}, line {b.line}" if b.path else f"line {b.line}"
                return f"This is already in the note: “{quote}” ({where})."
        for vid, amount in plan.already:
            if amount == "all" and vid.startswith("V") and vid[1:].isdigit():
                n = int(vid[1:]) - 1
                if 0 <= n < len(self._vault):
                    return f"This is already in [[{self._vault[n][0].removesuffix('.md')}]]."
        return "This is already in the note."


def _halved(budget: EditBudget) -> EditBudget:
    return replace(budget, outline=budget.outline // 2, related=budget.related // 2)


def _dropped(edit: PlannedEdit, why: str) -> str:
    return f"{edit.why or 'A change'}: left out ({why})"
