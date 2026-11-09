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
from paper_pile.core.ai.proposals import propose
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
    NoteEdit,
    NoteWriter,
    Target,
    VaultWriter,
    apply_batch_async,
    can_review,
    find_named,
    propose_one,
    redo_stale,
    review_text,
    undo,
)
from paper_pile.core.ai.vault.memory import load_memory, read_memory_file, save_memory, with_fact
from paper_pile.core.ai.vault.meta import VaultMeta
from paper_pile.core.ai.vault.plan import Choice, Plan, card_lines, choose, make_plan
from paper_pile.core.ai.vault.reply import Reply, note_link
from paper_pile.core.ai.vault.results import ResultSet
from paper_pile.core.ai.vault.run import RunResult, VaultAgent, run_plan
from paper_pile.core.ai.vault.scope import ScopeResolver
from paper_pile.core.ai.vault.tools import VaultTools
from paper_pile.core.ai.vault.understand import RequestContext, VaultRequest, understand_request
from paper_pile.core.config import scope_for
from paper_pile.core.daily import DEFAULT_FORMAT
from paper_pile.core.index import Index
from paper_pile.core.vault import VaultError

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
    memory: str = ""  # the memory file as it would be after a "remember" (saved on Save)
    content: str = ""  # the chat's previous answer, for a step that writes it into a note
    facts: tuple[str, ...] = ()  # a "remember" waiting for the permission
    attached: tuple[str, ...] = ()  # the notes a question about attached notes was about


APPLY, CANCEL, UNDO = "Apply all", "Cancel", "Undo"
ALLOW_OPTIONS = ("Allow always", "Allow this session", "Don't allow")  # the permission (§4.32)
_NO_CHOICE = Choice("", (), (), "auto")  # changes applied at once: nothing was asked
LINK_HERE = "Link them here"  # Related notes: the found notes as links in that note
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
    ``@folder/``; ``attached``: it carries a selection or a file — then it is about that text
    (unless scoped; the chat's answer can replace a selection). Attached notes do not stop it:
    a change to the attached note is the agent's edit (user 2026-11-09)."""
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


def with_target(request: VaultRequest, notes: Sequence[str], open_note: str) -> VaultRequest:
    """``request`` with its edits that name no notes pointed at the notes the message is
    about: the attached ones, else the open note when the edit searches for nothing. An edit
    with no target would otherwise reach across the whole vault (the model may leave
    ``notes`` empty for "this note")."""
    targets = tuple(notes)
    steps = []
    for s in request.steps:
        bare = s.action == "edit" and s.scope.empty and s.depends_on < 0 and not s.from_result
        use = targets or ((open_note,) if open_note and not s.terms else ())
        steps.append(replace(s, scope=replace(s.scope, notes=use)) if bare and use else s)
    return replace(request, steps=tuple(steps))


def no_target_question(request: VaultRequest, given: Sequence[str]) -> VaultRequest:
    """``request`` without its question when every step works on notes the user gave (named
    in its notes, or none named while some were given): which of them is never asked — the
    rule decides (attached first, else the active open note). A question about anything else
    (a step that searches or names other notes) stays."""
    names = {n.casefold() for n in given if n}
    if not request.question or not names:
        return request
    for s in request.steps:
        if s.terms or s.from_result or s.depends_on >= 0:
            return request
        sc = s.scope
        if sc.folders or sc.tags or sc.dates is not None or sc.linked_from or sc.links_to:
            return request
        if any(n.casefold() not in names for n in sc.notes):
            return request
    return replace(request, question="", options=())


def related_section(text: str, lines: list[str]) -> str:
    """``text`` with ``lines`` (``- [[link]]``) at the end of its ``Related`` section, or in
    a new one at the end of the note."""
    sec = find_named(text, "Related")
    if sec is None:
        return text.rstrip() + "\n\n## Related\n\n" + "\n".join(lines) + "\n"
    rows = text.split("\n")
    end = sec.end
    while end > sec.start and not rows[end - 1].strip():  # after its last line
        end -= 1
    return "\n".join([*rows[:end], *lines, *rows[end:]])


def question_text(choice: Choice) -> str:
    if choice.kind == "remote":  # the permission: one line, its options are the chips
        return choice.question
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
        self._remote_ok = False  # allowed for this session (the app window): never reset
        self._calls0 = 0  # the engine's call count when the current request began
        self.link_target = ""  # the note the last @vault request was about (Related notes)
        self._names: tuple[tuple[str, ...], str] = ((), "")  # (attached names, open note)
        self._given: frozenset[str] = frozenset()  # paths of the attached / open notes

    def reset(self) -> None:
        """A new or another chat: forget the last result and any open question (an "Allow
        this session" stays until the window closes)."""
        self.last = None
        self.pending = None

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
        """Why the agent may not read or edit the vault now (PLAN §4.32, §9): the AI runs on
        another computer and ``ai.remote_agent`` is not "yes" and this session was not allowed;
        "" when it may."""
        provider = self.engine.provider
        if getattr(provider, "local", True) or self._remote_ok:
            return ""
        config = self.engine.config
        if config is not None and config.get("ai.remote_agent", "no") == "yes":
            return ""
        where = f"{provider.label} at {provider.host}" if provider.host else provider.label
        return f"The agent may not read or edit your vault on {where} (not on this computer)."

    def _permission(self, pending: Pending) -> Turn:
        """The permission question in the chat: always (saved as the default), this session,
        or not."""
        choice = Choice(self.remote_notice(), ALLOW_OPTIONS, ("always", "session", "no"), "remote")
        return self._ask(replace(pending, choice=choice))

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
        from_note: str = "",
        notes: Sequence[str] = (),
        other_note: str = "",
    ) -> Turn | None:
        """The agent's answer to ``message``, or None: the chat answers it the usual way.
        ``from_note``: the note an ``@vault`` request is about (left out of its results;
        \"Link them here\" links the found notes into it). ``notes``: the names of the notes
        attached to the message (a change "to this note" goes to them)."""
        mode = agent_mode(
            self.engine.config.get("ai.vault_agent", "auto") if self.engine.config else "auto"
        )
        if (
            self.pending is None
            and message.strip().casefold() == LINK_HERE.casefold()
            and self.link_target
            and self.last is not None
        ):
            return await self._link_here(on_status or (lambda _t: None))
        # one of our own chips' answers (Apply all / Cancel / Undo) with nothing open: never a
        # new request (agy read "Apply all" as a new edit after a review that changed nothing)
        expired = self.pending is None and message.strip().casefold() in _OWN_ANSWERS
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
        if notes and not scopes:  # about the attached notes: never a vault search (rule 9)
            return await self._about_attached(message, notes, status)
        previous, answer = self._previous_answer()
        status("Reading the request")
        ctx = RequestContext(
            today=self.today(),
            folders=agent.folders(),
            tags=agent.tags(),
            open_note=open_note,
            other_note=other_note,
            attached=tuple(notes),
            last_result=self.last.compact(reasons=False)
            if self.last is not None and len(self.last)
            else "",
            scoped=scopes,
            memory=agent.memory,
            previous=previous,
        )
        request = await understand_request(self.engine, message, ctx)
        if request is None or not request.needs_vault or not request.steps:
            return None  # the usual chat answer (old @vault search included)
        facts = [s.detail for s in request.steps if s.action == "remember" and s.detail]
        if facts:  # a fact about the vault to keep: the memory file, after a review
            return await self._remember(message, facts)
        self.link_target = from_note
        request = with_target(with_scopes(request, scopes), notes, open_note)
        given_names = [*notes, open_note, other_note]
        request = no_target_question(request, given_names)
        self._given = self._paths_of(given_names)
        agent.given, agent.words = self._given, message
        content = answer if any(s.uses_answer for s in request.steps) else ""
        self._names = (tuple(notes), open_note)
        plan = make_plan(request, agent.tools.resolver, self.last, message, scopes)
        if plan.choice is not None:
            return self._ask(Pending(message, plan, plan.choice, content=content))
        return await self._run(agent, plan, message, status, stop, use_best=False, content=content)

    def _previous_answer(self) -> tuple[str, str]:
        """``(the user's message it replied to, its text)`` of the chat's last plain answer
        before this message; ("", "") when there is none to reuse (a review, a question, an
        error). The message goes to the understanding call, the text only to a change."""
        turns = getattr(self.engine, "turns", [])
        # the current message and its (empty) reply are the last two turns
        before = turns[:-2] if len(turns) >= 2 and turns[-1].role == "assistant" else turns[:-1]
        if len(before) < 2:
            return "", ""
        asked, said = before[-2], before[-1]
        kind = (said.vault or {}).get("kind")
        if asked.role != "user" or said.role != "assistant" or said.error or said.cut:
            return "", ""
        if kind not in (None, "chat") or not said.text.strip():
            return "", ""
        return " ".join(asked.text.split())[:200], said.text

    async def _resume(
        self,
        agent: VaultAgent,
        pending: Pending,
        value: str,
        status: Callable[[str], None],
        stop: Callable[[], bool],
    ) -> Turn | None:
        choice = pending.choice
        if choice.kind == "memory":
            if value != "save":
                return Turn("Not saved.", summary="Vault: cancelled", payload={"kind": "cancelled"})
            save_memory(self.engine.vault.root, pending.memory)
            return Turn(
                "Saved to the notes for the AI about this vault (Settings → AI).",
                summary="Vault: remembered",
                payload={"kind": "remembered"},
            )
        if choice.kind == "attached":  # the picked request, on the same attached notes
            return await self._about_attached(value, pending.attached, status)
        if choice.kind == "remote":
            if value == "no":
                return Turn(
                    "Not allowed: no note was read or changed.", summary="Vault: not allowed"
                )
            self._remote_ok = True
            config = self.engine.config
            if value == "always" and config is not None:  # the default permission (Settings)
                config.set("ai.remote_agent", "yes", scope_for("ai.remote_agent", "global"))
            if pending.facts:
                return await self._remember(pending.message, list(pending.facts))
            return await self._run(
                agent,
                pending.plan,
                pending.message,
                status,
                stop,
                use_best=pending.use_best,
                content=pending.content,
            )
        if choice.kind == "budget":
            if value == "narrow":
                return Turn(
                    "Tell me how to narrow it down: a folder, a tag or a period.", asked=True
                )
            return await self._run(
                agent,
                pending.plan,
                pending.message,
                status,
                stop,
                use_best=True,
                content=pending.content,
            )
        if choice.kind == "open":  # fold the picked option into the request and start again
            names, open_note = self._names  # the same notes as the message asked about
            return await self.handle(
                f"{pending.message}\nAnswer: {value}",
                scopes=[],
                attached=False,
                open_note=open_note,
                on_status=status,
                stop=stop,
                notes=names,
            )
        plan = choose(pending.plan, value, agent.tools.resolver)
        if plan.choice is not None:
            return self._ask(Pending(pending.message, plan, plan.choice, content=pending.content))
        return await self._run(
            agent,
            plan,
            pending.message,
            status,
            stop,
            use_best=pending.use_best,
            content=pending.content,
        )

    async def _about_attached(
        self, message: str, names: Sequence[str], status: Callable[[str], None]
    ) -> Turn | None:
        """A message with notes attached is about them (PLAN §4.32, CLAUDE.md rule 9): the
        Ask box's understanding call decides — answer (None: the plain chat answers with the
        notes) or change. A change goes to every attached note through the edit pipeline
        with the user's own words; an open choice of content is asked, never which note."""
        from paper_pile.core.ai.understand import understand

        writer = self.writer()
        notes: list[tuple[str, str, str]] = []  # (path, title, text)
        for name in dict.fromkeys(names):  # in the order attached
            path = next(iter(self._paths_of([name])), None)
            if path is None or any(path == p for p, _, _ in notes):
                continue
            try:
                text = writer.read(path)
            except (VaultError, OSError):
                continue
            notes.append((path, path.rsplit("/", 1)[-1].removesuffix(".md"), text))
        if not notes:
            return None
        status("Reading the request")
        shown = "\n\n".join(f"Note {title}:\n{text.strip()}" for _, title, text in notes)
        understood = await understand(self.engine, message, shown)
        if understood is None or understood.want == "answer":
            return None
        if not understood.complete and len(understood.options) >= 2:
            choice = Choice(understood.question, understood.options, understood.options, "attached")
            return self._ask(Pending(message, Plan([]), choice, attached=tuple(names)))
        self._given = frozenset(p for p, _, _ in notes)
        intent = replace(understood.intent(), scope="note")  # whole notes, no selection
        target = Target("change", "", message)
        batch = EditBatch(message, target)
        status("Preparing the changes")
        for path, title, text in notes:
            edit = await propose_one(self.engine, target, path, title, text, intent=intent)
            if edit.proposal is not None:
                batch.edits.append(edit)
            else:
                batch.failed.append((title, edit.error or "no change was made"))
                if edit.asked:
                    batch.asked.append(edit.asked)
        if not batch.ready:
            return Turn(review_text(batch), [p for p, _, _ in notes], "Vault: nothing changed")
        return await self._deliver(message, Plan([]), batch, status)

    def _only_given(self, plan: Plan) -> bool:
        """Does every step work only on notes the user gave (attached, open on screen), with
        no search? Those are the chat's direct notes: no permission question (PLAN §4.32)."""
        if not self._given:
            return False
        for ps in plan.steps:
            if ps.after >= 0:
                continue  # works on an earlier step's notes (checked there)
            if ps.search or ps.paths is None or not set(ps.paths) <= self._given:
                return False
        return True

    def _paths_of(self, names: Sequence[str]) -> frozenset[str]:
        from paper_pile.core.links import resolve_wikilink

        paths = self.engine.note_paths()
        return frozenset(p for n in names if n and (p := resolve_wikilink(n, "", paths)))

    async def _remember(self, message: str, facts: list[str]) -> Turn:
        """A fact about the vault to keep (PLAN_vault_agent §5.6), by the edit mode (PLAN
        §4.32): saved at once, or its editor opened with the change (review); a writer that
        cannot show it gets the chat's Save / Cancel."""
        if self.remote_notice():  # the agent edits the memory file too: allowed first
            return self._permission(Pending(message, Plan([]), _NO_CHOICE, facts=tuple(facts)))
        root = self.engine.vault.root
        before = read_memory_file(root)
        after = before
        for fact in facts:
            after = with_fact(after, fact)
        if after == before:
            return Turn("That is already in the notes for the AI.", summary="Vault: nothing new")
        added = [line for line in after.splitlines() if line not in before.splitlines()]
        diff = "\n".join(f"+ {line}" for line in added)
        if self._mode() == "auto":
            save_memory(root, after)
            return Turn(
                f"Saved to the notes for the AI about this vault:\n\n```diff\n{diff}\n```",
                summary="Vault: remembered",
                payload={"kind": "remembered"},
            )
        writer = self.writer()
        if can_review(writer) and await writer.review_memory(before, after):  # type: ignore[attr-defined]
            return Turn(
                "The change to the notes for the AI is open to save (Settings → AI).",
                summary="Vault: to remember",
                payload={"kind": "proposed"},
            )
        choice = Choice("Save it?", ("Save", "Cancel"), ("save", "cancel"), "memory")
        self.pending = Pending(message, Plan([]), choice, memory=after)
        return Turn(
            f"I would add this to the notes for the AI about this vault:\n\n```diff\n{diff}\n```",
            summary="Vault: to remember",
            asked=True,
            payload={"kind": "question", "chips": [chip("Save"), chip("Cancel")]},
        )

    async def _link_here(self, status: Callable[[str], None]) -> Turn:
        """The found notes as links in a Related section of the note the request came
        from (P30.42) — only notes it does not link to yet; a review, like any change."""
        target, last = self.link_target, self.last
        assert last is not None
        writer = self.writer()
        try:
            text = writer.read(target)
        except (VaultError, OSError):
            return Turn("That note is not there any more.", summary="Vault: nothing to link")
        linked = self._links_from(target)
        found = [i for i in last.sure() if i.path != target and i.path not in linked]
        if not found:
            return Turn("It already links to every note found.", summary="Vault: nothing to link")
        lines = [f"- [[{self.engine.link_name(i.path)}]]" for i in found]
        after = related_section(text, lines)
        proposal = propose(target, text, 0, len(text), after)
        title = target.rsplit("/", 1)[-1].removesuffix(".md")
        batch = EditBatch(LINK_HERE, Target("add", "Related", "link the related notes"))
        batch.edits.append(NoteEdit(target, title, text, proposal))
        return await self._deliver(LINK_HERE, Plan([]), batch, status)

    def _links_from(self, path: str) -> set[str]:
        agent = self._agent
        if agent is None:
            return set()
        rows = agent.tools.resolver.readable()
        paths = {r.path for r in rows}
        return set(agent.tools.resolver._links_out({path}, paths))

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

    def _mode(self) -> str:
        """``ai.edits`` (PLAN §4.32): "auto" (applied at once) or "ask" (review in the note)."""
        from paper_pile.core.ai.edits import edit_mode

        config = self.engine.config
        return edit_mode(config.get("ai.edits", "ask") if config is not None else "ask")

    async def _deliver(
        self, message: str, plan: Plan, batch: EditBatch, status: Callable[[str], None]
    ) -> Turn:
        """Changes ready: written at once (*Apply at once*) or shown in the notes for review
        (*Review in the note*) — never a question in the chat (PLAN §4.32). A writer that cannot
        show diffs (tools, tests) gets the old chat review."""
        if self._mode() == "auto":
            return await self._apply(Pending(message, plan, _NO_CHOICE, batch=batch), "all", status)
        writer = self.writer()
        if can_review(writer) and await writer.review(batch):  # type: ignore[attr-defined]
            return self._shown(batch)
        return self._review(message, plan, batch)

    def _shown(self, batch: EditBatch) -> Turn:
        """The chat's line for changes shown in the notes: where they wait, as links."""
        ready = batch.ready
        links = ", ".join(f"[{e.title}]({note_link(e.path)})" for e in ready if not e.new)
        new = [e for e in ready if e.new]
        lines = []
        if links:
            where = "in the note" if len(ready) == 1 else "in the notes"
            lines.append(f"The change is shown {where}: {links} — accept or reject it there.")
        if new:
            lines.append("New note to keep or reject: " + ", ".join(e.title for e in new) + ".")
        if batch.skipped:
            lines.append("Left out: " + "; ".join(f"{t} ({why})" for t, why in batch.skipped))
        if batch.failed:
            lines.append("Not changed: " + "; ".join(f"{t} ({why})" for t, why in batch.failed))
        n = len(ready)
        return Turn(
            "\n".join(lines),
            [e.path for e in ready if not e.new],
            f"Vault: {n} change{'s' if n != 1 else ''} shown in the note{'s' if n != 1 else ''}",
            payload={"kind": "proposed"},
        )

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
        auto = pending.choice is _NO_CHOICE  # Apply at once: no question was asked
        picks = None if isinstance(picked, str) else [int(n) for n in picked]
        done = await apply_batch_async(batch, picks, writer)
        lines: list[str] = []
        changed = [p for p in done.paths if p not in done.created]
        if changed:
            names = ", ".join(
                f"[{p.rsplit('/', 1)[-1].removesuffix('.md')}]({note_link(p)})" for p in changed
            )
            lines.append(f"Changed {len(changed)} note{'s' if len(changed) != 1 else ''}: {names}.")
        if done.created:
            lines.append(
                "New note: "
                + ", ".join(
                    f"[{p.rsplit('/', 1)[-1].removesuffix('.md')}]({note_link(p)})"
                    for p in done.created
                )
                + "."
            )
        if batch.skipped and auto:
            lines.append("Left out: " + "; ".join(f"{t} ({why})" for t, why in batch.skipped))
        if batch.failed and auto:
            lines.append("Not changed: " + "; ".join(f"{t} ({why})" for t, why in batch.failed))
        if done.failed:
            lines.append("Could not write: " + ", ".join(done.failed))
        if done.stale:  # changed since the diff was made: never written over — diffs made again
            status("Some notes changed meanwhile: making their changes again…")
            again = await redo_stale(self.engine, batch, done.stale, writer)
            names = ", ".join(e.title for e in done.stale)
            if again.ready and auto:  # once more at once; what changed again is left alone
                more = await apply_batch_async(again, None, writer)
                done.paths += more.paths
                done.before.update(more.before)
                done.after.update(more.after)
                if more.paths:
                    lines.append(f"Changed after a second look (edited meanwhile): {names}.")
                if more.stale:
                    lines.append(f"{names} kept changing and were left as they are.")
                again = EditBatch(again.request, again.target)
            if again.ready:
                turn = self._review(pending.message, pending.plan, again)
                intro = "\n".join(lines) + "\n\n" if lines else ""
                again_note = f"{names} changed after the diff was made; here is the change again:"
                turn.text = f"{intro}{again_note}\n\n{turn.text}"
                return turn
            lines.append(f"{names} changed after the diff was made and were left as they are.")
        if done.before:  # a typed "Undo" still puts them back (no chip: PLAN §4.32)
            choice = Choice("Undo?", (UNDO,), ("undo",), "undo")
            self.pending = Pending(pending.message, pending.plan, choice, applied=done)
        if done.before and not auto:
            n = len(done.before)
            lines.append(
                f"Reply “{UNDO}” to put the {n} note{'s' if n != 1 else ''} back as they were."
            )
        chips = [chip(UNDO)] if done.before and not auto else []
        if done.paths and not auto:
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
        content: str = "",
    ) -> Turn:
        # beyond the notes the user gave, no note text leaves the computer before it is allowed
        if not self._only_given(plan) and self.remote_notice():
            return self._permission(
                Pending(message, plan, _NO_CHOICE, use_best=use_best, content=content)
            )
        many = len(plan.steps) > 1

        def progress(step: int, stage: str, done: int, total: int) -> None:
            label = STAGES.get(stage, stage.removeprefix("loop: ").split("(", 1)[0].capitalize())
            count = f" {done}/{total}" if total else ""
            prefix = f"Step {step + 1}: " if many else ""
            n = self.calls()
            status(f"{prefix}{label}{count}… · {n} model call{'s' if n != 1 else ''}")

        skip = frozenset({self.link_target}) if self.link_target else frozenset()
        result: RunResult = await run_plan(
            agent,
            plan,
            message,
            on_progress=progress,
            use_best=use_best,
            stop=stop,
            skip=skip,
            content=content,
        )
        if result.choice is not None:
            return self._ask(
                Pending(message, plan, result.choice, use_best=use_best, content=content)
            )
        if result.last is not None:
            self.last = result.last
        batch = next((r.review for r in result.replies if r.review is not None), None)
        if batch is not None and batch.ready:
            return await self._deliver(message, plan, batch, status)
        steps = card_lines(plan)
        titles = [f"{i}. {line.split('. ', 1)[-1]}" for i, line in enumerate(steps, 1)]
        replies, offset = [], 0
        for r in result.replies:  # one numbering for the whole answer: one source per pill
            replies.append(relabel(r, offset))
            offset += len(r.sources)
        text = reply_markdown(replies, titles) or "Stopped."
        chips = hint_chips(replies[-1], message) if replies else []
        if self.link_target and self.last is not None and self.last.sure():
            chips.insert(0, chip(LINK_HERE))  # Related notes: link them into the note
        if self.last is not None and len(self.last):  # ask it again later (P30.41)
            chips.append({"label": "Save this search", "save": message})
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
