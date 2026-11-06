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
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from typing import TYPE_CHECKING, Literal

from paper_pile.core.ai.vault.candidates import Gatherer
from paper_pile.core.ai.vault.cards import CardMaker, CardStore, card_search, card_summaries
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
}


@dataclass(slots=True)
class Pending:
    """A question the agent asked; the next message answers it."""

    message: str
    plan: Plan
    choice: Choice
    use_best: bool = False


@dataclass(slots=True)
class Turn:
    """What the agent made of one message, for the chat."""

    text: str
    sources: list[str] = field(default_factory=list)  # note paths the answer is from
    summary: str = ""  # the info line ("Vault: 4 notes · 2 steps")
    asked: bool = False  # the turn is a question to the user


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
    the unverified-citations line and the next-step hints."""
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
        if reply.hints:
            parts.append("Next: " + " · ".join(h.label for h in reply.hints))
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

    def reset(self) -> None:
        """A new or another chat: forget the last result and any open question."""
        self.last = None
        self.pending = None

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
        agent = self.agent()
        if agent is None:
            return None
        status = on_status or (lambda _t: None)

        pending, self.pending = self.pending, None
        if pending is not None:
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
            last_result=self.last.compact() if self.last is not None and len(self.last) else "",
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
        return Turn(question_text(pending.choice), asked=True, summary="Vault: a question first")

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
        many = len(plan.steps) > 1

        def progress(step: int, stage: str, done: int, total: int) -> None:
            label = STAGES.get(stage, stage.removeprefix("loop: ").split("(", 1)[0].capitalize())
            count = f" {done}/{total}" if total else ""
            prefix = f"Step {step + 1}: " if many else ""
            status(f"{prefix}{label}{count}…")

        result: RunResult = await run_plan(
            agent, plan, message, on_progress=progress, use_best=use_best, stop=stop
        )
        if result.choice is not None:
            return self._ask(Pending(message, plan, result.choice, use_best=use_best))
        if result.last is not None:
            self.last = result.last
        titles = [f"{i}. {line.split('. ', 1)[-1]}" for i, line in enumerate(card_lines(plan), 1)]
        text = reply_markdown(result.replies, titles) or "Stopped."
        sources = list(dict.fromkeys(s.path for r in result.replies for s in r.sources))
        if not sources:  # a list of notes cites nothing: the chat lists the notes found
            sources = [i.path for r in result.replies for i in r.results.sure()]
            sources = list(dict.fromkeys(sources))
        notes = len(self.last) if self.last is not None else 0
        word = "note" if notes == 1 else "notes"
        summary = f"Vault: {notes} {word}" + (f" · {len(plan.steps)} steps" if many else "")
        return Turn(text, sources, summary)
