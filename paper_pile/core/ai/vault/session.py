"""The vault agent inside the chat (PLAN_vault_agent §5, P30.49): the bridge between
``AiEngine.answer`` and the agent, so the chat, regenerate and the saved history all go
through the same path.

For each chat message: should the agent look (``ai.vault_agent``: ``auto`` for messages
without attachments and for ``@`` scopes, ``at`` only for ``@vault`` / ``@folder/``, ``off``
never)? If so: understand → plan → run, and the replies become one chat answer (text,
sources, notices, next-step hints). When the model says the vault is not needed, cannot be
asked, or the message has nothing for the agent, the chat answers exactly as before (the
caller's own path). A question the agent asks (which note? the best 60?) is answered by the
next message: a number or an option's text. The last result set is kept for follow-ups.

No UI imports; the engine is passed in (no import of ``engine`` at module level).
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from paper_pile.core.ai.chats import moved_path
from paper_pile.core.ai.vault.candidates import Gatherer
from paper_pile.core.ai.vault.cards import (
    CardMaker,
    CardStore,
    card_search,
    card_summaries,
    rename_tree,
)
from paper_pile.core.ai.vault.cite import _LABELS, Source
from paper_pile.core.ai.vault.edits import (
    Applied,
    EditBatch,
    NoteWriter,
    VaultWriter,
    apply_batch,
    redo_stale,
    review_text,
    undo,
)
from paper_pile.core.ai.vault.memory import load_memory
from paper_pile.core.ai.vault.meta import VaultMeta
from paper_pile.core.ai.vault.plan import Choice, Plan, card_lines, choose, make_plan
from paper_pile.core.ai.vault.reply import Reply
from paper_pile.core.ai.vault.results import ResultSet
from paper_pile.core.ai.vault.run import RunResult, VaultAgent, run_plan
from paper_pile.core.ai.vault.scope import ScopeResolver
from paper_pile.core.ai.vault.tools import VaultTools
from paper_pile.core.ai.vault.understand import RequestContext, VaultRequest, understand_request
from paper_pile.core.daily import DEFAULT_FORMAT
from paper_pile.core.index import Index

if TYPE_CHECKING:
    from paper_pile.core.ai.engine import AiEngine

log = logging.getLogger("paper_pile.ai.vault.session")

Mode = Literal["auto", "at", "off"]
MODES: tuple[Mode, ...] = ("auto", "at", "off")
STAGES = {  # progress as the chat's status line shows it
    "search": "Searching the notes",
    "judge": "Checking which notes fit",
    "judge more": "Looking a bit wider",
    "cards": "Reading the notes",
    "merge": "Putting the summary together",
    "extract": "Gathering the facts",
    "propose": "Preparing the changes",
}


@dataclass(slots=True)
class Pending:
    """A question the agent asked; the next message answers it."""

    message: str
    plan: Plan
    choice: Choice
    use_best: bool = False
    batch: EditBatch | None = None  # a review: changes waiting for the user (M6)
    applied: Applied | None = None  # an applied change the user may undo


APPLY, CANCEL, UNDO = "Apply all", "Cancel", "Undo"
EXCERPT_CHARS = 240  # of a cited part kept for its hover preview
EXPIRED = (  # an answer to a review / undo that is no longer open
    "That change is no longer open (the app was restarted, or another message came in "
    "between). Ask for the change again."
)
_OWN_ANSWERS = {APPLY.casefold(), CANCEL.casefold(), UNDO.casefold()}


def review_answer(text: str, count: int) -> list[int] | str | None:
    """The user's answer to a review: ``"all"``, ``"cancel"``, the note numbers picked
    (``"1, 3"``), or None when the message is something else (a new request)."""
    t = " ".join(text.split()).casefold().rstrip(".")
    if t == APPLY.casefold():
        return "all"
    if t == CANCEL.casefold():
        return "cancel"
    parts = [p.strip() for p in t.replace(" ", ",").split(",") if p.strip()]
    if parts and all(p.isdigit() for p in parts):
        picks = sorted({int(p) for p in parts if 1 <= int(p) <= count})
        return picks or None
    return None


def review_question(batch: EditBatch) -> str:
    n = len(batch.ready)
    pick = "the numbers of the notes to change (like 1, 3)" if n > 1 else ""
    choices = [f"“{APPLY}”"] + ([pick] if pick else []) + [f"“{CANCEL}”"]
    reply = f"Reply {', '.join(choices[:-1])} or {choices[-1]}."
    return f"{review_text(batch)}\n\nNothing is changed yet. {reply}"


@dataclass(slots=True)
class Turn:
    """What the agent made of one message, for the chat."""

    text: str
    sources: list[str] = field(default_factory=list)  # note paths the answer is from
    summary: str = ""  # the info line ("Vault: 4 notes · 2 steps")
    asked: bool = False  # the turn is a question to the user
    payload: dict[str, Any] = field(default_factory=dict)  # SavedTurn.vault (cites, chips…)


def chip(label: str, send: str = "", open_paths: Sequence[str] = ()) -> dict[str, Any]:
    """A chip under the answer: clicking it sends ``send`` as the next message (the same path
    as typing it), or opens ``open_paths``."""
    out: dict[str, Any] = {"label": label}
    if open_paths:
        out["open"] = list(open_paths)
    else:
        out["send"] = send or label
    return out


def cite_rows(sources: Sequence[Source]) -> list[dict[str, Any]]:
    """The citations as the chat file keeps them (P30.48): enough to open the note at the
    cited lines and to find them again after edits (``anchor``)."""
    return [
        {
            "n": s.n,
            "path": s.path,
            "title": s.title,
            "heading": s.heading,
            "start": s.start,
            "end": s.end,
            "anchor": s.anchor,
            "excerpt": " ".join(s.text.split())[:EXCERPT_CHARS],  # the hover preview
        }
        for s in sources
    ]


def relabel(reply: Reply, offset: int) -> Reply:
    """``reply`` with its citation labels moved up by ``offset``: the steps of one answer
    share one numbering, so every pill in it names one source."""
    if not offset or not reply.sources:
        return reply
    text = _LABELS.sub(
        lambda m: "[" + ", ".join(str(int(n) + offset) for n in m.group(1).split(",")) + "]",
        reply.text,
    )
    sources = [replace(s, n=s.n + offset) for s in reply.sources]
    checked = reply.checked
    if checked is not None:
        checked = replace(
            checked,
            text=text,
            used=[n + offset for n in checked.used],
            unverified=[n + offset for n in checked.unverified],
        )
    return replace(reply, text=text, sources=sources, checked=checked)


def hint_chips(reply: Reply, message: str) -> list[dict[str, Any]]:
    """The reply's hints as chips (data-made, §3.5): each sends a message the agent already
    understands, or opens notes."""
    out: list[dict[str, Any]] = []
    for h in reply.hints:
        if h.kind == "action" and h.value == "open":
            out.append(chip(h.label, open_paths=[i.path for i in reply.results.sure()][:10]))
        elif h.kind == "action" and h.value == "summarise":
            out.append(chip(h.label, "Summarise these notes"))
        elif h.kind == "action" and h.value == "extract":
            out.append(chip(h.label, "Make a table of these notes"))
        elif h.kind == "scope" and not h.value:
            out.append(chip(h.label, f"@vault {message}"))
        elif h.kind == "scope":
            out.append(chip(h.label, f"Only the ones in @{h.value}/"))
        elif h.kind == "near":
            where = h.value if h.value.startswith("#") else f"@{h.value}/"
            out.append(chip(h.label, f"{message} {where}"))
    return out


def agent_mode(value: object) -> Mode:
    return value if value in MODES else "auto"


def wants_agent(mode: Mode, scoped: bool, attached: bool) -> bool:
    """Should the agent look at this message? ``scoped``: it carries ``@vault`` /
    ``@folder/``; ``attached``: it carries a selection, notes or files — then it is about
    those (unless scoped)."""
    if mode == "off":
        return False
    if scoped:
        return True
    return mode == "auto" and not attached


def picked_option(choice: Choice, text: str) -> str | None:
    """The value of the option ``text`` picks: its number (1-based) or its text (case and
    spaces ignored); None when the message is not an answer to the question."""
    t = " ".join(text.split()).casefold().rstrip(".")
    if t.isdigit() and 1 <= int(t) <= len(choice.options):
        return choice.values[int(t) - 1]
    for opt, value in zip(choice.options, choice.values, strict=True):
        if t == " ".join(opt.split()).casefold() or t == value.casefold():
            return value
    return None


def with_scopes(request: VaultRequest, scopes: list[str]) -> VaultRequest:
    """``request`` with the message's ``@folder/`` scopes on every step that has no folder of
    its own and finds its own notes (the user pointed at the folder; the model may forget)."""
    folders = tuple(s.strip("/") for s in scopes if s.strip("/"))
    if not folders:
        return request
    steps = tuple(
        replace(s, scope=replace(s.scope, folders=folders))
        if not s.scope.folders and s.depends_on < 0 and not s.from_result and s.action != "meta"
        else s
        for s in request.steps
    )
    return replace(request, steps=steps)


def question_text(choice: Choice) -> str:
    lines = [choice.question, ""]
    lines += [f"{i}. {opt}" for i, opt in enumerate(choice.options, 1)]
    lines += ["", "Reply with a number or the option's name."]
    return "\n".join(lines)


def reply_markdown(replies: list[Reply], titles: list[str]) -> str:
    """The step replies as one chat answer: each step's text, then its sources, notices,
    the unverified-citations line. Next-step hints are chips (``payload["chips"]``), not text."""
    blocks: list[str] = []
    many = len(replies) > 1
    for title, reply in zip(titles, replies, strict=False):
        parts: list[str] = []
        if many:
            parts.append(f"**{title}**")
        parts.append(reply.text)
        if reply.sources:
            used = set(reply.checked.used) if reply.checked else {s.n for s in reply.sources}
            listed = [s for s in reply.sources if s.n in used] or reply.sources
            parts.append("Sources: " + " · ".join(s.label for s in listed))
        for note in reply.notices:
            parts.append(f"_{note}_")
        if reply.unverified_note:
            parts.append(f"_{reply.unverified_note}_")
        blocks.append("\n\n".join(parts))
    return "\n\n---\n\n".join(blocks)


class VaultSession:
    """One per engine (one chat at a time). Built lazily: nothing runs until the agent is
    asked. ``today`` is injectable for tests."""

    def __init__(self, engine: "AiEngine", today: Callable[[], date] = date.today) -> None:
        self.engine = engine
        self.today = today
        self.last: ResultSet | None = None
        self.pending: Pending | None = None
        self._agent: VaultAgent | None = None
        self._remote_ok = False  # this chat's user agreed to send notes to a remote backend
        self._calls0 = 0  # the engine's call count when the current request began

    def reset(self) -> None:
        """A new or another chat: forget the last result, any open question and the remote
        agreement (asked again in the next chat)."""
        self.last = None
        self.pending = None
        self._remote_ok = False

    def _last_vault_kind(self) -> str:
        """The kind of the chat's newest vault answer before this message ("" if none)."""
        turns = getattr(self.engine, "turns", [])
        for turn in reversed(turns[:-1]):  # the message itself is the last turn
            if turn.role == "assistant":
                return str(turn.vault.get("kind", "")) if turn.vault else ""
        return ""

    def renamed(self, old: str, new: str) -> None:
        """A note or folder moved: the last result, an open review and note cards follow."""
        if self.last is not None:
            items = [replace(i, path=moved_path(i.path, old, new)) for i in self.last.items]
            self.last = ResultSet(self.last.request, items)
        if self.pending is not None and self.pending.batch is not None:
            for edit in self.pending.batch.edits:
                edit.path = moved_path(edit.path, old, new)
        if self._agent is not None:
            rename_tree(self._agent.maker.store, old, new)

    def calls(self) -> int:
        """Model calls the current request has made so far (understanding included)."""
        return max(0, getattr(self.engine, "calls_made", 0) - self._calls0)

    def remote_notice(self) -> str:
        """The notice before the first vault job of a chat when the backend is not on this
        computer (PLAN_vault_agent §9); "" when it is local or the user already agreed."""
        provider = self.engine.provider
        if getattr(provider, "local", True) or self._remote_ok:
            return ""
        agent = self._agent
        most = agent.budgets.candidates if agent is not None else 60
        where = f"{provider.label} at {provider.host}" if provider.host else provider.label
        return (
            f"Looking through your vault sends parts of your notes (up to {most} notes) to "
            f"{where}, which is not on this computer. Go on?"
        )

    # ---- the agent -----------------------------------------------------------------------------

    @property
    def index(self) -> Index | None:
        ix = self.engine.index
        return ix if isinstance(ix, Index) else None

    def agent(self) -> VaultAgent | None:
        """The agent over the app's index (None without one: the agent needs the index)."""
        ix = self.index
        if ix is None:
            return None
        if self._agent is None:
            cfg = self.engine.config
            daily = str(cfg.get("vault.daily_notes_folder", "") or "") if cfg else ""
            fmt = (
                str(cfg.get("vault.daily_notes_format", DEFAULT_FORMAT) or DEFAULT_FORMAT)
                if cfg
                else DEFAULT_FORMAT
            )
            resolver = ScopeResolver(
                ix,
                lambda rel: self.engine.policy().may_read(rel),
                daily_folder=daily,
                daily_format=fmt,
            )
            tools = VaultTools(ix, resolver, self.engine.read_note, self.today)
            store = CardStore(self.engine.vault.root)
            maker = CardMaker(self.engine, store, self.engine.read_note, ix.hashes, ix.title)
            gatherer = Gatherer(
                tools, card_search(store, ix.hashes), card_summaries(store, ix.hashes)
            )
            self._agent = VaultAgent(
                self.engine, tools, gatherer, maker, VaultMeta(ix, resolver), today=self.today
            )
        self._agent.memory = load_memory(self.engine.vault.root)
        self._agent.writer = self.writer()
        self._agent.link = self.engine.link_name
        return self._agent

    # ---- one message ---------------------------------------------------------------------------

    async def handle(
        self,
        message: str,
        *,
        scopes: list[str],
        attached: bool,
        open_note: str = "",
        on_status: Callable[[str], None] | None = None,
        stop: Callable[[], bool] = lambda: False,
    ) -> Turn | None:
        """The agent's answer to ``message``, or None: the chat answers it the usual way."""
        mode = agent_mode(
            self.engine.config.get("ai.vault_agent", "auto") if self.engine.config else "auto"
        )
        expired = (  # one of our own chips' answers, but the question it answered is gone
            self.pending is None
            and message.strip().casefold() in _OWN_ANSWERS
            and self._last_vault_kind() in ("review", "applied")
        )
        if expired:
            return Turn(EXPIRED, summary="Vault: nothing open", payload={"kind": "expired"})
        agent = self.agent()
        if agent is None:
            return None
        status = on_status or (lambda _t: None)
        self._calls0 = getattr(self.engine, "calls_made", 0)  # this request's calls start here

        pending, self.pending = self.pending, None
        if pending is not None and pending.batch is not None:
            picked = review_answer(message, len(pending.batch.ready))
            if picked is not None:
                return await self._apply(pending, picked, status)
        elif pending is not None and pending.applied is not None:
            if picked_option(pending.choice, message) is not None:
                return self._undo(pending.applied)
        elif pending is not None:
            value = picked_option(pending.choice, message)
            if value is not None:
                return await self._resume(agent, pending, value, status, stop)

        if not wants_agent(mode, bool(scopes), attached):
            return None
        status("Reading the request")
        ctx = RequestContext(
            today=self.today(),
            folders=agent.folders(),
            tags=agent.tags(),
            open_note=open_note,
            last_result=self.last.compact(reasons=False)
            if self.last is not None and len(self.last)
            else "",
            scoped=scopes,
            memory=agent.memory,
        )
        request = await understand_request(self.engine, message, ctx)
        if request is None or not request.needs_vault or not request.steps:
            return None  # the usual chat answer (old @vault search included)
        request = with_scopes(request, scopes)
        plan = make_plan(request, agent.tools.resolver, self.last, message, scopes)
        if plan.choice is not None:
            return self._ask(Pending(message, plan, plan.choice))
        return await self._run(agent, plan, message, status, stop, use_best=False)

    async def _resume(
        self,
        agent: VaultAgent,
        pending: Pending,
        value: str,
        status: Callable[[str], None],
        stop: Callable[[], bool],
    ) -> Turn | None:
        choice = pending.choice
        if choice.kind == "remote":
            if value != "go":
                return Turn("Cancelled: nothing was sent.", summary="Vault: cancelled")
            self._remote_ok = True
            return await self._run(
                agent, pending.plan, pending.message, status, stop, use_best=pending.use_best
            )
        if choice.kind == "budget":
            if value == "narrow":
                return Turn(
                    "Tell me how to narrow it down: a folder, a tag or a period.", asked=True
                )
            return await self._run(
                agent, pending.plan, pending.message, status, stop, use_best=True
            )
        if choice.kind == "open":  # fold the picked option into the request and start again
            return await self.handle(
                f"{pending.message}\nAnswer: {value}",
                scopes=[],
                attached=False,
                on_status=status,
                stop=stop,
            )
        plan = choose(pending.plan, value, agent.tools.resolver)
        if plan.choice is not None:
            return self._ask(Pending(pending.message, plan, plan.choice))
        return await self._run(
            agent, plan, pending.message, status, stop, use_best=pending.use_best
        )

    def _ask(self, pending: Pending) -> Turn:
        self.pending = pending
        choice = pending.choice
        return Turn(
            question_text(choice),
            asked=True,
            summary="Vault: a question first",
            payload={"kind": "question", "chips": [chip(o) for o in choice.options]},
        )

    # ---- changes to notes (M6) -----------------------------------------------------------------

    def writer(self) -> NoteWriter:
        """The app's writer (open tabs, autosave, index, history) when it set one, else the
        files directly (tools, tests)."""
        given = getattr(self.engine, "note_writer", None)
        return given if given is not None else VaultWriter(self.engine.vault)

    def _review(self, message: str, plan: Plan, batch: EditBatch) -> Turn:
        choice = Choice("Apply the changes?", (APPLY, CANCEL), ("all", "cancel"), "review")
        self.pending = Pending(message, plan, choice, batch=batch)
        n = len(batch.ready)
        return Turn(
            review_question(batch),
            [e.path for e in batch.ready if not e.new],
            f"Vault: {n} change{'s' if n != 1 else ''} to review",
            asked=True,
            payload={
                "kind": "review",
                "chips": [chip(APPLY), chip(CANCEL)],
                "review": [
                    {"n": i, "title": e.title, "path": e.path, "new": e.new}
                    for i, e in enumerate(batch.ready, 1)
                ],
            },
        )

    async def _apply(
        self, pending: Pending, picked: list[int] | str, status: Callable[[str], None]
    ) -> Turn:
        assert pending.batch is not None
        batch = pending.batch
        if picked == "cancel":
            return Turn(
                "Cancelled: no note was changed.",
                summary="Vault: cancelled",
                payload={"kind": "cancelled"},
            )
        status("Applying the changes…")
        writer = self.writer()
        done = apply_batch(batch, None if picked == "all" else list(picked), writer)  # type: ignore[arg-type]
        lines: list[str] = []
        if done.paths:
            names = ", ".join(p.rsplit("/", 1)[-1][:-3] for p in done.paths)
            lines.append(
                f"Changed {len(done.paths)} note{'s' if len(done.paths) != 1 else ''}: {names}."
            )
        if done.created:
            lines.append("New note: " + ", ".join(done.created))
        if done.failed:
            lines.append("Could not write: " + ", ".join(done.failed))
        if done.stale:  # changed since the diff was made: never written over — diffs made again
            status("Some notes changed meanwhile: making their changes again…")
            again = await redo_stale(self.engine, batch, done.stale, writer)
            names = ", ".join(e.title for e in done.stale)
            if again.ready:
                turn = self._review(pending.message, pending.plan, again)
                intro = "\n".join(lines) + "\n\n" if lines else ""
                again_note = f"{names} changed after the diff was made; here is the change again:"
                turn.text = f"{intro}{again_note}\n\n{turn.text}"
                return turn
            lines.append(f"{names} changed after the diff was made and were left as they are.")
        if done.before:
            n = len(done.before)
            choice = Choice("Undo?", (UNDO,), ("undo",), "undo")
            self.pending = Pending(pending.message, pending.plan, choice, applied=done)
            lines.append(
                f"Reply “{UNDO}” to put the {n} note{'s' if n != 1 else ''} back as they were."
            )
        chips = [chip(UNDO)] if done.before else []
        if done.paths:
            chips.append(chip("Open them", open_paths=done.paths[:10]))
        return Turn(
            "\n".join(lines) or "Nothing was changed.",
            done.paths,
            "Vault: changes applied",
            payload={"kind": "applied", "chips": chips},
        )

    def _undo(self, applied: Applied) -> Turn:
        restored, kept = undo(applied, self.writer())
        lines = []
        if restored:
            lines.append(
                f"Put back {len(restored)} note{'s' if len(restored) != 1 else ''} as they were."
            )
        if kept:
            lines.append("Changed again since, so left as they are: " + ", ".join(kept))
        if applied.created:
            lines.append(
                "New notes are kept: "
                + ", ".join(applied.created)
                + " (delete them to the trash if not needed)."
            )
        return Turn(
            "\n".join(lines) or "Nothing to undo.",
            restored,
            "Vault: undone",
            payload={"kind": "undone"},
        )

    async def _run(
        self,
        agent: VaultAgent,
        plan: Plan,
        message: str,
        status: Callable[[str], None],
        stop: Callable[[], bool],
        *,
        use_best: bool,
    ) -> Turn:
        notice = self.remote_notice()
        if notice:  # no note text leaves the computer before the user agrees (§9)
            choice = Choice(notice, ("Go on", "Cancel"), ("go", "cancel"), "remote")
            return self._ask(Pending(message, plan, choice, use_best=use_best))
        many = len(plan.steps) > 1

        def progress(step: int, stage: str, done: int, total: int) -> None:
            label = STAGES.get(stage, stage.removeprefix("loop: ").split("(", 1)[0].capitalize())
            count = f" {done}/{total}" if total else ""
            prefix = f"Step {step + 1}: " if many else ""
            n = self.calls()
            status(f"{prefix}{label}{count}… · {n} model call{'s' if n != 1 else ''}")

        result: RunResult = await run_plan(
            agent, plan, message, on_progress=progress, use_best=use_best, stop=stop
        )
        if result.choice is not None:
            return self._ask(Pending(message, plan, result.choice, use_best=use_best))
        if result.last is not None:
            self.last = result.last
        batch = next((r.review for r in result.replies if r.review is not None), None)
        if batch is not None and batch.ready:
            return self._review(message, plan, batch)
        steps = card_lines(plan)
        titles = [f"{i}. {line.split('. ', 1)[-1]}" for i, line in enumerate(steps, 1)]
        replies, offset = [], 0
        for r in result.replies:  # one numbering for the whole answer: one source per pill
            replies.append(relabel(r, offset))
            offset += len(r.sources)
        text = reply_markdown(replies, titles) or "Stopped."
        chips = hint_chips(replies[-1], message) if replies else []
        payload = {
            "kind": "answer",
            "cites": cite_rows([s for r in replies for s in r.sources]),
            "chips": chips,
            "steps": steps if many else [],
            "calls": self.calls(),
        }
        sources = list(dict.fromkeys(s.path for r in result.replies for s in r.sources))
        if not sources:  # a list of notes cites nothing: the chat lists the notes found
            sources = [i.path for r in result.replies for i in r.results.sure()]
            sources = list(dict.fromkeys(sources))
        notes = len(self.last) if self.last is not None else 0
        word = "note" if notes == 1 else "notes"
        calls = self.calls()
        summary = f"Vault: {notes} {word}" + (f" · {len(plan.steps)} steps" if many else "")
        summary += f" · {calls} model call{'s' if calls != 1 else ''}"
        return Turn(text, sources, summary, payload=payload)
