"""The AI engine: everything the AI features do apart from drawing (PLAN §4.26).

The chat pane, the AI commands and *Write with AI* hand it what the user asked and what the
editor shows; it keeps the open chat (its turns, saving, opening), builds the context and the
messages, and streams the answer from the provider. The UI never builds a prompt or trims the
history itself, so another front end (a TUI) reuses this unchanged. No UI imports here.
"""

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from paper_pile.core.ai.access import (
    AccessDeniedError,
    AccessPolicy,
    Grant,
    grant_now,
    load_grant,
    paths_in,
    revoke,
    save_grant,
    unique,
)
from paper_pile.core.ai.attachments import FileRef
from paper_pile.core.ai.chats import (
    SavedChat,
    SavedQuote,
    SavedTurn,
    chat_title,
    chats_folder,
    delete_chat,
    delete_chats,
    expired_chats,
    list_chats,
    load_chat,
    new_chat_id,
    save_chat,
)
from paper_pile.core.ai.context import (
    DIVIDER,
    BacklinkSource,
    Context,
    EditorSnapshot,
    best_section,
    build_context,
    cut_to_tokens,
    estimate_tokens,
    extract_mentions,
    system_head,
)
from paper_pile.core.ai.edits import FINISHED, EditTooLongError, clean_reply, reply_room
from paper_pile.core.ai.factory import chat_model, generation_options, make_provider
from paper_pile.core.ai.instructions import system_instruction
from paper_pile.core.ai.notecache import NoteCache
from paper_pile.core.ai.provider import (
    ChatMessage,
    Finish,
    Health,
    Provider,
    ProviderError,
    Reasoning,
    is_local_host,
)
from paper_pile.core.ai.selection_ask import AskTurn
from paper_pile.core.ai.structured import parse_json_object
from paper_pile.core.commands import StreamInsert
from paper_pile.core.config import Config
from paper_pile.core.index import query_words
from paper_pile.core.links import resolve_wikilink, wikilink_to
from paper_pile.core.settings import language_name
from paper_pile.core.vault import Vault

log = logging.getLogger("paper_pile.ai.engine")

VAULT_TAG = re.compile(r"(?<![\w@])@vault\b", re.IGNORECASE)  # search the vault for the message
VAULT_HITS = 3
ASK_AGAIN_S = 60.0  # an unknown context length is asked again after this long
MIN_ANSWER = 256  # tokens an answer may always take (``num_predict``), however full the window
BUSY = "The AI is still answering — wait for it or press Stop."
SUMMARIZING = "Summarizing earlier messages…"
CUT_OFF = "*(cut off: the answer reached its length limit)*"

HISTORY_TURNS = 12  # at most this many earlier messages go with a new one (ai.history_turns)
DEFAULT_BUDGET = 6000
# The model's context window: ``ai.num_ctx``, or automatic = what the model takes, at most
# AUTO_WINDOW (a bigger window needs more memory). Always sent to Ollama, so that what is counted
# here is what the model gets (Ollama's own default is smaller and cuts silently).
AUTO_WINDOW = 8192
MESSAGE_OVERHEAD = 4  # tokens a message costs besides its text (role, separators)
CONTEXT_SHARE = 0.6  # of the prompt's room, notes may take this much; history gets the rest
COMPACT_AT = 0.6  # earlier messages above this share of the prompt's room get summarized
EARLIER_NOTE_SHARE = 0.25  # of the notes budget, per note attached to an earlier message
KEEP_RECENT = 4  # messages never summarized (the last two exchanges)
COMPACT_PROMPT = (
    "You keep the memory of a conversation between a user and an assistant in a note app. "
    "Write a short summary of the conversation below so it can go on without it: the user's "
    "goals and questions, facts and decisions, names of notes, and anything left open. Plain "
    "markdown bullet points, at most 200 words, no introduction."
)
NOTE_ONLY = (
    "\n\nReply with only the text to put into the note: no introduction, no comments about what "
    "you did, and no code block around the answer."
)


@dataclass(frozen=True, slots=True)
class Selection:
    """Text attached to the next message: an editor selection or a block."""

    text: str
    label: str  # "From [[a]]" (or "Selected text" without a note)
    note: str = ""  # the note it came from
    kind: str = "Selected text"  # or "Code block", "Math block", "Diagram"
    detail: str = ""  # replaces the size when set (a block's text includes its fences)

    def size(self) -> str:
        if self.detail:
            return self.detail
        lines = len(self.text.strip().splitlines())
        return f"{lines} lines" if lines > 1 else f"{len(self.text.strip())} chars"

    def preview(self, limit: int = 300) -> str:
        t = self.text.strip()
        return t if len(t) <= limit else t[:limit] + "…"


@dataclass(frozen=True, slots=True)
class Outgoing:
    """A message on its way: what is shown in the chat, and what the model gets with it."""

    turn: SavedTurn
    attached: str  # the attached texts, for the context
    notes: list[str]  # attached notes, as link names


class AiEngine:
    def __init__(
        self,
        vault: Vault,
        config: Config | None,
        index: BacklinkSource | None = None,
        *,
        user_name: Callable[[], str] = lambda: "",
        provider_factory: Callable[[Config | None], Provider] = make_provider,
        access_dir: Path | None = None,  # where ai_access.json is (None: the config folder)
    ) -> None:
        self.vault = vault
        self.config = config
        self.index = index
        self._user_name = user_name
        self._factory = provider_factory
        self.provider: Provider = provider_factory(config)
        self.notes = NoteCache(vault)
        self._access_dir = access_dir
        self._policy: AccessPolicy | None = None
        self._max_context: dict[str, tuple[int | None, float]] = {}  # model -> (length, asked)
        self.turns: list[SavedTurn] = []
        self.summary = ""  # "Summary so far": replaces the first ``summarized`` turns
        self.summarized = 0
        self._busy: asyncio.Task[object] | None = None  # the task an answer streams in
        self.last_usage: tuple[int | None, int | None] = (None, None)  # prompt, answer tokens
        self._compact_failed = -1  # turns when the last summary failed (no new try for a while)
        self.chat_id = new_chat_id()
        self.created = time.time()

    # ---- settings ------------------------------------------------------------------------

    def setting(self, key: str, default: object) -> object:
        return self.config.get(key, default) if self.config is not None else default

    def language(self) -> str:
        return language_name(str(self.setting("general.language", "en")))

    def budget(self) -> int:
        return int(str(self.setting("ai.context_budget", DEFAULT_BUDGET)))

    def model(self) -> str:
        return chat_model(self.provider, self.config)

    def reload(self) -> None:
        """The AI settings changed (host / model): build the provider again."""
        self.provider = self._factory(self.config)
        self._max_context.clear()

    async def window(self) -> int:
        """The context window in tokens: ``ai.num_ctx`` when set, else the model's own limit
        capped at ``AUTO_WINDOW`` (asked once per model)."""
        chosen = int(str(self.setting("ai.num_ctx", 0) or 0))
        if chosen > 0:
            return chosen
        model = self.model()
        known, asked = self._max_context.get(model, (None, -ASK_AGAIN_S))
        if model not in self._max_context or (
            known is None and time.monotonic() - asked >= ASK_AGAIN_S
        ):  # unknown (Ollama was down, or loading): asked again a minute later
            known = await self.provider.context_length(model)
            self._max_context[model] = (known, time.monotonic())
        return min(known, AUTO_WINDOW) if known else AUTO_WINDOW

    @staticmethod
    def answer_room(window: int) -> int:
        """Tokens kept free for the answer."""
        return max(512, window // 4)

    async def prompt_room(self) -> int:
        """Tokens the prompt (system, history, question) may use."""
        window = await self.window()
        return window - self.answer_room(window)

    async def context_budget(self) -> int:
        """Tokens of note text per message: ``ai.context_budget``, but never more than its share
        of the prompt's room."""
        return min(self.budget(), int(await self.prompt_room() * CONTEXT_SHARE))

    async def health(self) -> Health:
        return await self.provider.health()

    def model_problem(self, health: Health) -> str:
        """What to tell the user when the chosen model is not among the installed ones ("" when
        it is, or nothing is known): before a message fails on it."""
        if not health.ok or not health.models:
            return ""
        model = self.model()
        names = set(health.models)
        if model in names or f"{model}:latest" in names:
            return ""
        return (
            f"The model “{model}” is not installed — run `ollama pull {model}`, or pick another "
            "one above."
        )

    # ---- access (PLAN §4.26) ---------------------------------------------------------------

    def policy(self) -> AccessPolicy:
        """What the AI may read in this vault (from ``ai_access.json``; kept until changed)."""
        if self._policy is None:
            grant = load_grant(self.vault.root, self._access_dir)
            self._policy = AccessPolicy(self.vault.root, grant, self.chats_dir())
        return self._policy

    def consent_text(self) -> str:
        """What the Allow card says: what is read, and where it goes when that is not this
        computer (``ai.host`` is another machine)."""
        text = f"To answer, the AI reads the notes of “{self.vault.root.name}” on this computer."
        host = self.provider.host
        if host and not is_local_host(host):
            text += f" They are sent to {host}, another computer."
        return text + " Limit or take it back any time in Settings → AI → Access."

    def has_access(self) -> bool:
        return self.policy().granted

    def allow(self) -> None:
        """The user allowed the AI to read this vault."""
        grant_now(self.vault.root, self._access_dir)
        self.access_changed()

    def revoke_access(self) -> None:
        revoke(self.vault.root, self._access_dir)
        self.access_changed()

    def access_changed(self) -> None:
        """``ai_access.json`` (or the memories folder) changed: read it again."""
        self._policy = None

    def _require_access(self) -> AccessPolicy:
        policy = self.policy()
        if not policy.granted:
            raise AccessDeniedError("Allow the AI to read this vault first (Settings → AI).")
        return policy

    def read_note(self, path: str) -> str | None:
        """A note's text for the AI: None when it may not read it (path, type, ``ai: false``)."""
        policy = self.policy()
        if not policy.may_read(path):
            return None
        text = self.notes.read(path)
        return text if text is not None and policy.may_send(path, text) else None

    def may_use(self, path: str) -> bool:
        """May text from note ``path`` go to the AI without the user picking it (an automatic
        selection chip, a quote sent again)? Not from a note it may not read (PLAN §4.26)."""
        if not path:
            return False
        if self.has_access():
            return self.read_note(path) is not None
        # not allowed yet (sending asks first): what a first grant would let it read
        text = self.notes.read(path)
        first = AccessPolicy(self.vault.root, Grant(""), self.chats_dir())
        return text is not None and first.may_send(path, text)

    def readable_paths(self) -> list[str]:
        """The notes the AI may read (by path; their properties are checked on reading)."""
        policy = self.policy()
        return [p for p in self.note_paths() if policy.may_read(p)]

    def paths_to_ask(self, text: str) -> list[Path]:
        """Folders / files outside the vault that a message names and that are not granted yet:
        the chat asks for each before sending (PLAN §4.26)."""
        policy = self.policy()
        return [p for p in paths_in(text, self.vault.root) if not policy.covers(p)]

    def allow_path(self, path: Path) -> None:
        """The user allowed the AI to read ``path`` (outside the vault) from now on."""
        grant = load_grant(self.vault.root, self._access_dir)
        if grant is None:
            return  # the vault itself comes first (confirm_access)
        grant.allow_paths = unique([*grant.allow_paths, str(path.expanduser().resolve())])
        save_grant(self.vault.root, grant, self._access_dir)
        self.access_changed()

    def outside_text(self, text: str) -> list[tuple[str, str]]:
        """``(path, text)`` of the granted outside files a message names (a folder: its files of
        the allowed types), at most the context budget in all."""
        policy = self.policy()
        named = [p for p in paths_in(text, self.vault.root) if policy.covers(p)]
        if not named:
            return []
        files = policy.outside_files()
        left = self.budget()  # tokens
        out: list[tuple[str, str]] = []
        for root in named:
            for path in [root] if root.is_file() else [f for f in files if root in f.parents]:
                body = policy.read_outside(path)
                if body is None or not body.strip() or left <= 0:
                    continue
                kept = cut_to_tokens(body, left)
                out.append((str(path), kept))
                left -= estimate_tokens(kept)
        return out

    def outside_files(self) -> list[Path]:
        """Files of the granted outside folders, for the + menu."""
        return self.policy().outside_files()

    def outside_ref(self, path: Path) -> FileRef | None:
        """A granted outside file attached like an uploaded one (None when not readable)."""
        text = self.policy().read_outside(path)
        return FileRef(str(path), text) if text is not None and text.strip() else None

    # ---- the open chat -------------------------------------------------------------------

    def chats_dir(self) -> Path:
        """Where chats are saved (``ai.chats_folder``, else the vault's ``.memory``)."""
        return chats_folder(self.vault.root, str(self.setting("ai.chats_folder", "") or ""))

    @property
    def title(self) -> str:
        return chat_title(self.turns)

    def new_chat(self) -> None:
        self.turns = []
        self.summary, self.summarized = "", 0
        self._compact_failed = -1
        self.chat_id, self.created = new_chat_id(), time.time()

    def open_chat(self, chat_id: str) -> bool:
        """Make a saved chat the open one; False when it cannot be read."""
        if chat_id == self.chat_id:
            return True
        chat = load_chat(self.chats_dir(), chat_id)
        if chat is None:
            return False
        self.turns = list(chat.turns)
        self.summary, self.summarized = chat.summary, chat.summarized
        self._compact_failed = -1
        self.chat_id, self.created = chat.id, chat.created
        return True

    def delete_chat(self, chat_id: str) -> bool:
        """Move a saved chat to the trash; True when it was the open one (now a new chat)."""
        delete_chat(self.vault, self.chats_dir(), chat_id)
        return self.forget(chat_id)

    def forget(self, *chat_ids: str) -> bool:
        """These chats are gone (deleted elsewhere): start afresh if the open one was among
        them. True when it was."""
        if self.chat_id not in chat_ids:
            return False
        self.new_chat()
        return True

    def save(self) -> None:
        """Write the open chat out (nothing for an empty one, or when saving is off)."""
        if not any(t.text.strip() for t in self.turns):
            return
        if not self.setting("ai.save_chats", True):
            return
        turns = list(self.turns)
        save_chat(
            self.chats_dir(),
            SavedChat(
                self.chat_id,
                chat_title(turns),
                self.created,
                time.time(),
                turns,
                self.summary,
                self.summarized,
            ),
        )

    def prune(self) -> int:
        """Move chats older than ``ai.keep_chats_days`` to the trash (never the open one)."""
        days = int(str(self.setting("ai.keep_chats_days", 0) or 0))
        old = [c.id for c in expired_chats(list_chats(self.chats_dir()), days, time.time())]
        return delete_chats(self.vault, self.chats_dir(), [c for c in old if c != self.chat_id])

    # ---- attachments ---------------------------------------------------------------------

    def note_paths(self) -> list[str]:
        """Every note of the vault (cached; see :class:`NoteCache`)."""
        return self.notes.paths()

    def notes_changed(self) -> None:
        """A note was created, renamed or deleted."""
        self.notes.invalidate()

    def link_name(self, path: str) -> str:
        """How ``path`` is written in a ``[[link]]`` ("" without a path)."""
        return wikilink_to(path, "", set(self.note_paths())) if path else ""

    def selection(self, text: str, path: str) -> Selection:
        name = self.link_name(path)
        return Selection(text, f"From [[{name}]]" if name else "Selected text", name)

    def block(self, kind: str, lang: str, text: str, path: str) -> Selection:
        """A code / math / diagram block attached like a selection (with its fences)."""
        body = text.strip("\n")
        if kind == "math":
            fenced, label = f"$$\n{body}\n$$", "Math block"
        elif kind == "diagram":
            fenced, label = f"```mermaid\n{body}\n```", "Diagram"
        else:
            fenced, label = f"```{lang}\n{body}\n```", "Code block"
        n = len(body.splitlines()) or 1
        name = self.link_name(path)
        return Selection(
            fenced, f"From [[{name}]]" if name else label, name, label, f"{n} line{'s' * (n != 1)}"
        )

    # ---- chat ----------------------------------------------------------------------------

    def add_message(
        self,
        text: str,
        selections: Sequence[Selection] = (),
        notes: Sequence[str] = (),
        files: Sequence[FileRef] = (),
    ) -> Outgoing:
        """Add the user's message (with what is attached to it) to the open chat."""
        known = set(self.note_paths())
        names = [wikilink_to(p, "", known) for p in notes if p in known]
        label = "\n".join(
            [f"{p.label}: [{p.kind}]" for p in selections]
            + [f"[[{n}]]" for n in names]
            + [f"{f.name}: [File]" for f in files]
        )
        attached = "\n\n".join(
            [f"{p.label}:\n{p.text.strip()}" for p in selections]
            + [f"File {f.name}:\n{f.text.strip()}" for f in files]
        )
        outside = self.outside_text(text) if self.has_access() else []
        if outside:
            labels = [f"{p}: [Outside file]" for p, _ in outside]
            texts = [f"File {p}:\n{body.strip()}" for p, body in outside]
            label = "\n".join([label, *labels] if label else labels)
            attached = "\n\n".join([attached, *texts] if attached else texts)
        quotes = [SavedQuote(p.label, p.kind, p.size(), p.text, p.note) for p in selections]
        turn = SavedTurn("user", text, label, quotes=quotes, notes=names)
        self.turns.append(turn)
        return Outgoing(turn, attached, names)

    def chat_from_box(self, selected: str, path: str, turns: Sequence[AskTurn]) -> None:
        """The Ask box's conversation becomes the open chat (and is saved like any chat): the
        selection goes with its first message, as a quote (PLAN §4.27)."""
        if not turns:
            return
        self.new_chat()
        quote = self.selection(selected, path)
        first, *rest = turns
        self.turns.append(
            SavedTurn(
                "user",
                first.text,
                f"{quote.label}: [{quote.kind}]",
                quotes=[SavedQuote(quote.label, quote.kind, quote.size(), quote.text, quote.note)],
            )
        )
        self.turns.extend(SavedTurn(t.role, t.text) for t in rest)
        self.save()

    def start_reply(self) -> SavedTurn:
        reply = SavedTurn("assistant", "")
        self.turns.append(reply)
        return reply

    def chat_context(
        self,
        snap: EditorSnapshot,
        question: str,
        attached: str = "",
        notes: Sequence[str] = (),
        *,
        include_tabs: bool = False,
        budget: int | None = None,
    ) -> Context:
        """What goes with the newest message: its attachments, the open note, the notes it
        mentions or attaches, ``@vault`` hits, tabs, linked notes. Notes attached to earlier
        messages go with those messages (:meth:`past_text`), not here."""
        policy = self._require_access()
        found = self.vault_search(question)
        question = VAULT_TAG.sub(" ", question)
        current = snap.path if policy.may_send(snap.path, snap.text) else None
        return build_context(
            self.vault,
            current_path=current,
            current_text=snap.text if current else "",
            selection=attached or (snap.selection if current else ""),  # chips: sent on purpose
            mentions=list(dict.fromkeys([*extract_mentions(question), *notes])),
            found=found,
            open_tabs=[(p, t) for p, t in snap.tabs if policy.may_send(p, t)],
            include_tabs=include_tabs,
            index=self.index,
            budget=budget if budget is not None else self.budget(),
            paths=self.readable_paths(),
            read=self.read_note,
        )

    def vault_search(self, question: str) -> list[tuple[str, str, str]]:
        """``@vault`` in a message: ``(path, title, text)`` of the best few notes for it from the
        vault's index that the AI may read, each as its section with most of the question's
        words (whole notes would not fit: the notes' share holds about one)."""
        if not VAULT_TAG.search(question):
            return []
        search = getattr(self.index, "search", None)
        if not callable(search):
            return []
        asked = VAULT_TAG.sub(" ", question)
        out: list[tuple[str, str, str]] = []
        for hit in search(asked, limit=VAULT_HITS * 4, any_words=True):
            text = self.read_note(hit.path)
            if text is None:
                continue
            heading, part = best_section(text, query_words(asked))
            out.append((hit.path, f"{hit.path} § {heading}" if heading else hit.path, part))
            if len(out) == VAULT_HITS:
                break
        return out

    def system_prompt(self) -> str:
        """The same for every message of a chat (nothing that changes per message), so the
        model can reuse the work it did for the start of the conversation."""
        return system_head(
            self._user_name(), self.language(), system_instruction(self.config, self.vault.root)
        )

    @staticmethod
    def with_notes(context: Context, message: str) -> str:
        """``message`` with the context's notes in front of it."""
        notes = context.notes_block()
        return notes + DIVIDER + message if notes else message

    def past_text(self, turn: SavedTurn, *, notes: bool = True) -> str:
        """An earlier message as the model sees it again, with what was attached to it: its
        quotes and (``notes``) the notes it attached or mentioned, each cut to a share of the
        budget. They stay in their own message, so the prompt's start does not change while
        they do not (PLAN §4.26). A quote from a note the AI may not read (now) is left out: it
        went with its own message only."""
        if turn.role != "user":
            return turn.text
        parts = [
            f"{q.label}:\n{q.text.strip()}" if self._quote_ok(q) else f"{q.label}: [left out]"
            for q in turn.quotes
        ]
        if notes:
            cap = int(self.budget() * EARLIER_NOTE_SHARE)
            for name in dict.fromkeys([*turn.notes, *extract_mentions(turn.text)]):
                path = resolve_wikilink(name, "", self.note_paths())
                text = self.read_note(path) if path else None
                if text is not None and text.strip():
                    parts.append(f"Note {path}:\n{cut_to_tokens(text.strip(), cap)}")
        return "\n\n".join(parts) + DIVIDER + turn.text if parts else turn.text

    def _quote_ok(self, quote: SavedQuote) -> bool:
        if not quote.note:
            return True  # loose text (no note), or a file
        path = resolve_wikilink(quote.note, "", self.note_paths())
        return path is None or self.may_use(path)

    def chat_messages(
        self, context: Context, question: str, room: int | None = None
    ) -> list[ChatMessage]:
        """The messages for the newest question: the fixed system prompt, the earlier turns and
        the question with its notes. Earlier turns are taken newest first while they fit in
        ``room`` tokens (all of the prompt; None = no limit), at most ``ai.history_turns``;
        failed and empty ones are left out."""
        system = ChatMessage("system", self.system_prompt() + self._summary_text())
        ask = ChatMessage("user", self.with_notes(context, question))
        keep = int(str(self.setting("ai.history_turns", HISTORY_TURNS)))
        left = None if room is None else room - message_tokens([system, ask])
        past: list[ChatMessage] = []
        for turn in reversed(self.turns[self.summarized : -2]):
            if len(past) >= keep:
                break
            if turn.error or not turn.text.strip():
                continue
            msg = ChatMessage("user" if turn.role == "user" else "assistant", self.past_text(turn))
            if left is not None:
                left -= message_tokens([msg])
                if left < 0:
                    break
            past.append(msg)
        return [system, *reversed(past), ask]

    async def answer(
        self,
        reply: SavedTurn,
        out: Outgoing,
        snap: EditorSnapshot,
        *,
        include_tabs: bool = False,
        on_status: Callable[[str], None] | None = None,
    ) -> AsyncIterator[str]:
        """Answer ``out``: the reply's text grows as the pieces arrive (also yielded).
        ``on_status`` hears what happens before the answer starts (a summary being made)."""
        question = out.turn.text
        window = await self.window()
        room = window - self.answer_room(window)
        compacted = await self.compact_if_needed(room, on_status)
        context = self.chat_context(
            snap,
            question,
            out.attached,
            out.notes,
            include_tabs=include_tabs,
            budget=min(self.budget(), int(room * CONTEXT_SHARE)),
        )
        messages = self.chat_messages(context, question, room)
        used = message_tokens(messages)
        reply.summary = f"{context.summary()} · {short_count(used)} / {short_count(window)} tokens"
        if compacted:
            reply.summary += " · earlier messages summarized"
        reply.sources = list(dict.fromkeys(p.path for p in context.parts if p.path))

        def reasoned(text: str) -> None:
            reply.reasoning += text

        finish: list[str] = []
        async for piece in self.stream(messages, window, reasoned, finish.append):
            reply.text += piece
            yield piece
        if finish and finish[-1] != FINISHED:
            reply.cut = True
            reply.text = (reply.text + "\n\n" + CUT_OFF).strip()

    # ---- redoing the last exchange -------------------------------------------------------

    def _outgoing_for(self, turn: SavedTurn) -> Outgoing:
        """What an earlier user message sent along, rebuilt from the saved turn."""
        attached = [f"{q.label}:\n{q.text.strip()}" for q in turn.quotes]
        attached += [f"File {p}:\n{body.strip()}" for p, body in self.outside_text(turn.text)]
        return Outgoing(turn, "\n\n".join(attached), list(turn.notes))

    def regenerate(self) -> Outgoing | None:
        """Drop the last answer so the last message is answered again (None when the chat does
        not end with a message and its answer)."""
        if len(self.turns) < 2 or self.turns[-1].role != "assistant":
            return None
        asked = self.turns[-2]
        if asked.role != "user":
            return None
        self.turns.pop()
        return self._outgoing_for(asked)

    def take_back(self) -> SavedTurn | None:
        """Remove the last message (and its answer) to edit and send it again; the message."""
        end = len(self.turns) - (1 if self.turns and self.turns[-1].role == "assistant" else 0)
        if end < 1 or self.turns[end - 1].role != "user":
            return None
        asked = self.turns[end - 1]
        del self.turns[end - 1 :]
        self.summarized = min(self.summarized, len(self.turns))
        return asked

    # ---- compaction ----------------------------------------------------------------------

    def _summary_text(self) -> str:
        return f"\n\nSummary of the conversation so far:\n{self.summary}" if self.summary else ""

    def _past(self, end: int) -> list[SavedTurn]:
        """The turns from the last summary up to ``end`` that would be sent again."""
        return [t for t in self.turns[self.summarized : end] if not t.error and t.text.strip()]

    async def compact_if_needed(
        self, room: int, on_status: Callable[[str], None] | None = None
    ) -> bool:
        """Summarize the earlier messages when they take more than ``COMPACT_AT`` of ``room``
        (the newest exchange, still being answered, does not count). True when it did. After a
        failed summary it waits ``KEEP_RECENT`` messages before trying again (the earlier
        messages are trimmed meanwhile), so a broken model does not slow every message."""
        if self._compact_failed >= 0 and len(self.turns) < self._compact_failed + KEEP_RECENT:
            return False
        past = self._past(len(self.turns) - 2)
        tokens = sum(
            estimate_tokens(self.past_text(t, notes=False)) + MESSAGE_OVERHEAD for t in past
        )
        if tokens <= room * COMPACT_AT:
            return False
        if on_status is not None:
            on_status(SUMMARIZING)
        try:
            return await self.compact(len(self.turns) - 2, room)
        except ProviderError:
            log.warning("could not summarize the chat", exc_info=True)
            self._compact_failed = len(self.turns)
            return False

    async def compact(self, end: int | None = None, room: int | None = None) -> bool:
        """Fold the turns before the last ``KEEP_RECENT`` (counted back from ``end``, default all
        turns) into "Summary so far", with one model call. The turns stay in the chat; only what
        the model is sent changes. False when there is too little to fold; ProviderError when the
        call fails. When the turns do not all fit, the oldest go first (never the earlier
        summary)."""
        self._require_access()  # the summary sends the chat (with its quotes) to the model
        end = len(self.turns) if end is None else end
        upto = end - KEEP_RECENT
        if upto <= self.summarized:
            return False
        room = room if room is not None else await self.prompt_room()
        limit = max(0, room - estimate_tokens(COMPACT_PROMPT) - 2 * MESSAGE_OVERHEAD)
        head = f"Earlier summary:\n{self.summary}" if self.summary else ""
        left = limit - estimate_tokens(head) - 1
        lines: list[str] = []
        for turn in reversed(self.turns[self.summarized : upto]):  # newest first while they fit
            if turn.error or not turn.text.strip():
                continue
            who = "User" if turn.role == "user" else "Assistant"
            line = f"{who}: {self.past_text(turn, notes=False)}"
            left -= estimate_tokens(line) + 1
            if left < 0:
                break
            lines.append(line)
        transcript = "\n\n".join([head, *reversed(lines)] if head else reversed(lines))
        if not lines and not head:
            transcript = cut_to_tokens(self.past_text(self.turns[upto - 1], notes=False), limit)
        messages = [ChatMessage("system", COMPACT_PROMPT), ChatMessage("user", transcript)]
        summary = "".join([piece async for piece in self.stream(messages)]).strip()
        if not summary:
            return False
        self.summary, self.summarized = summary, upto
        self._compact_failed = -1
        return True

    # ---- answers that edit a note --------------------------------------------------------

    def edit_from_reply(self, reply: SavedTurn) -> tuple[str, str, str] | None:
        """``(note path, old text, new text)`` when ``reply`` answers a message with exactly one
        attached selection from a note: the answer can replace it (shown as a diff first). A
        selection answered with one code block gets the block's content."""
        i = next((n for n, t in enumerate(self.turns) if t is reply), -1)
        asked = self.turns[i - 1] if i > 0 else None
        if asked is None or asked.role != "user" or len(asked.quotes) != 1:
            return None
        if reply.error or reply.cut:  # an answer that did not finish never edits a note
            return None
        quote = asked.quotes[0]
        path = resolve_wikilink(quote.note, "", self.note_paths()) if quote.note else None
        new = clean_reply(reply.text, quote.text)
        if path is None or not new.strip():
            return None
        return path, quote.text, new

    @staticmethod
    def stopped(reply: SavedTurn) -> None:
        reply.cut = True
        reply.text = (reply.text + "\n\n*(stopped)*").strip()

    @staticmethod
    def failed(reply: SavedTurn, message: str) -> None:
        """The answer failed: what arrived stays (marked), or the turn says why."""
        if reply.text.strip():
            reply.cut = True
            reply.text = f"{reply.text.rstrip()}\n\n*(stopped: {message})*"
        else:
            reply.error, reply.text = True, message

    # ---- the provider --------------------------------------------------------------------

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        window: int | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        on_finish: Callable[[str], None] | None = None,
        *,
        schema: Mapping[str, Any] | None = None,
        think: bool | None = None,
        temperature: float | None = None,
        max_answer: int | None = None,
    ) -> AsyncIterator[str]:
        """The model's answer to ``messages``, with the chosen model, the options and the
        context window (``window``, else :meth:`window`); the answer may use what the prompt
        leaves of it (at most ``max_answer`` tokens when set). Reasoning goes to
        ``on_reasoning`` (dropped without it), never into the answer; why the answer ended goes
        to ``on_finish`` (not called when it was stopped or failed). ``schema`` (a JSON
        schema), ``think`` and ``temperature`` override the settings for this call (PLAN
        §4.29). The backend's token counts are kept in :attr:`last_usage`. One answer at a time:
        while another task streams, raises ProviderError."""
        current = asyncio.current_task()
        other = self._busy
        if other is not None and other is not current and not other.done():
            raise ProviderError(BUSY)
        size = window or await self.window()
        room = max(MIN_ANSWER, size - message_tokens(messages))
        if max_answer is not None:
            room = min(room, max_answer)
        options = replace(
            generation_options(self.config),
            num_ctx=size,
            num_predict=room,
            schema=schema,
            think=think,
        )
        if temperature is not None:
            options = replace(options, temperature=temperature)
        self._busy = current
        try:
            async for piece in self.provider.chat(messages, model=self.model(), options=options):
                if isinstance(piece, Reasoning):
                    if on_reasoning is not None:
                        on_reasoning(piece.text)
                elif isinstance(piece, Finish):
                    self.last_usage = (piece.prompt_tokens, piece.eval_tokens)
                    if on_finish is not None:
                        on_finish(piece.reason)
                else:
                    yield piece
        finally:
            if self._busy is current:
                self._busy = None

    async def ask_json(
        self,
        messages: Sequence[ChatMessage],
        schema: Mapping[str, Any],
        *,
        max_answer: int = 512,
        window: int | None = None,
    ) -> dict[str, Any] | None:
        """The model's answer to ``messages`` as a JSON object following ``schema`` (sent to the
        backend, which constrains the answer to it; no reasoning, temperature 0). None when the
        answer was cut off or is not a JSON object — the caller decides what then. Raises
        ProviderError like :meth:`stream`."""
        finish: list[str] = []
        parts = [
            piece
            async for piece in self.stream(
                messages,
                window,
                on_finish=finish.append,
                schema=schema,
                think=False,
                temperature=0.0,
                max_answer=max_answer,
            )
        ]
        if finish != [FINISHED]:
            return None
        return parse_json_object("".join(parts))

    # ---- AI commands (answers written into the note) -------------------------------------

    async def command_messages(
        self,
        spec: StreamInsert,
        *,
        path: str,
        text: str,
        caret: int,
        selected: str = "",
        question: str = "",
    ) -> list[ChatMessage]:
        """The messages for an AI command run in note ``path`` (``text``, caret at ``caret``).
        Raises :class:`AccessDeniedError` when the AI may not read that note."""
        if not self._require_access().may_send(path, text):
            raise AccessDeniedError(
                "The AI may not read this note (its type, an exclusion, or ai: false)."
            )
        source = spec.source if spec.source != "auto" else ("selection" if selected else "note")
        given = selected if source == "selection" else ""
        task = question or spec.instruction
        rules = "" if spec.ask else NOTE_ONLY
        system = ChatMessage("system", self.system_prompt() + rules)
        ask = task + (f"\n\nText:\n{given}" if given else "")
        budget = await self.context_budget()
        if spec.replace_selection:  # the answer rewrites ``given``: both must fit the window
            window = await self.window()
            need = message_tokens([system, ChatMessage("user", ask)])
            need += reply_room(estimate_tokens(given))
            if need > window:
                raise EditTooLongError(
                    f"The text is too long for this model (about {short_count(need)} tokens with "
                    f"the answer; the window holds {short_count(window)}). Select less."
                )
            budget = min(budget, window - need)  # notes only in the room that is left
        context = build_context(  # the selection goes with the task, not twice
            self.vault,
            current_path=path,
            current_text=text,
            index=self.index,
            budget=budget,
            paths=self.readable_paths(),
            read=self.read_note,
        )
        return [system, ChatMessage("user", self.with_notes(context, ask))]

    # ---- the Ask box under a selection (PLAN §4.27) --------------------------------------

    async def selection_messages(
        self, *, path: str, text: str, selected: str, turns: Sequence[AskTurn]
    ) -> list[ChatMessage]:
        """The messages for the Ask box's mini chat about ``selected`` in note ``path``
        (``text``): the selection goes with the first question, the note's context in front of
        it; later turns follow as they are. When it does not fit the window, the oldest exchanges
        after the first go; a selection too long even alone raises :class:`EditTooLongError`.
        Raises :class:`AccessDeniedError` when the AI may not read that note."""
        if not self._require_access().may_send(path, text):
            raise AccessDeniedError(
                "The AI may not read this note (its type, an exclusion, or ai: false)."
            )
        system = ChatMessage("system", self.system_prompt())
        first, *later = turns
        ask = f"The user selected this text in the note:\n\n{selected}{DIVIDER}{first.text}"
        window = await self.window()
        room = window - self.answer_room(window)

        def need(rest: Sequence[AskTurn]) -> int:
            msgs = [system, ChatMessage("user", ask), *(ChatMessage(t.role, t.text) for t in rest)]
            return message_tokens(msgs)

        while later and need(later) > room:
            later = later[2:]  # one question and its answer, oldest first
        if need(later) > room:
            raise EditTooLongError(
                f"The selected text is too long for this model (about {short_count(need(later))} "
                f"tokens; the window holds {short_count(window)}). Select less."
            )
        context = build_context(
            self.vault,
            current_path=path,
            current_text=text,
            index=self.index,
            budget=max(0, min(await self.context_budget(), room - need(later))),
            paths=self.readable_paths(),
            read=self.read_note,
        )
        rest = [ChatMessage(t.role, t.text) for t in later]
        return [system, ChatMessage("user", self.with_notes(context, ask)), *rest]


def message_tokens(messages: Sequence[ChatMessage]) -> int:
    """About how many tokens ``messages`` take (text estimate plus each message's overhead)."""
    return sum(estimate_tokens(m.content) + MESSAGE_OVERHEAD for m in messages)


def short_count(tokens: int) -> str:
    """``850``, ``1.5k``, ``8k``, ``128k`` (k = 1024, as context windows are named)."""
    if tokens < 1024:
        return str(tokens)
    k = tokens / 1024
    shown = f"{k:.0f}" if k >= 10 else f"{k:.1f}".removesuffix(".0")
    return shown + "k"
