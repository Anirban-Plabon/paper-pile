"""The AI engine: everything the AI features do apart from drawing (PLAN §4.26).

The chat pane, the AI commands and *Write with AI* hand it what the user asked and what the
editor shows; it keeps the open chat (its turns, saving, opening), builds the context and the
messages, and streams the answer from the provider. The UI never builds a prompt or trims the
history itself, so another front end (a TUI) reuses this unchanged. No UI imports here.
"""

import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

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
    BacklinkSource,
    Context,
    EditorSnapshot,
    build_context,
    estimate_tokens,
    extract_mentions,
)
from paper_pile.core.ai.factory import chat_model, generation_options, make_provider
from paper_pile.core.ai.instructions import system_instruction
from paper_pile.core.ai.provider import ChatMessage, Health, Provider
from paper_pile.core.commands import StreamInsert
from paper_pile.core.config import Config
from paper_pile.core.links import wikilink_to
from paper_pile.core.settings import language_name
from paper_pile.core.vault import Vault

log = logging.getLogger("paper_pile.ai.engine")

HISTORY_TURNS = 12  # at most this many earlier messages go with a new one (ai.history_turns)
DEFAULT_BUDGET = 6000
# The model's context window: ``ai.num_ctx``, or automatic = what the model takes, at most
# AUTO_WINDOW (a bigger window needs more memory). Always sent to Ollama, so that what is counted
# here is what the model gets (Ollama's own default is smaller and cuts silently).
AUTO_WINDOW = 8192
MESSAGE_OVERHEAD = 4  # tokens a message costs besides its text (role, separators)
CONTEXT_SHARE = 0.6  # of the prompt's room, notes may take this much; history gets the rest
BEFORE_CARET_CHARS = 4000  # "Continue writing" sees this much of the text before the caret
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
    ) -> None:
        self.vault = vault
        self.config = config
        self.index = index
        self._user_name = user_name
        self._factory = provider_factory
        self.provider: Provider = provider_factory(config)
        self._max_context: dict[str, int | None] = {}  # model -> its context length
        self.turns: list[SavedTurn] = []
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
        if model not in self._max_context:
            self._max_context[model] = await self.provider.context_length(model)
        known = self._max_context[model]
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

    # ---- the open chat -------------------------------------------------------------------

    def chats_dir(self) -> Path:
        """Where chats are saved (``ai.chats_folder``, else the vault's ``.memory``)."""
        return chats_folder(self.vault.root, str(self.setting("ai.chats_folder", "") or ""))

    @property
    def title(self) -> str:
        return chat_title(self.turns)

    def new_chat(self) -> None:
        self.turns = []
        self.chat_id, self.created = new_chat_id(), time.time()

    def open_chat(self, chat_id: str) -> bool:
        """Make a saved chat the open one; False when it cannot be read."""
        if chat_id == self.chat_id:
            return True
        chat = load_chat(self.chats_dir(), chat_id)
        if chat is None:
            return False
        self.turns = list(chat.turns)
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
            SavedChat(self.chat_id, chat_title(turns), self.created, time.time(), turns),
        )

    def prune(self) -> int:
        """Move chats older than ``ai.keep_chats_days`` to the trash (never the open one)."""
        days = int(str(self.setting("ai.keep_chats_days", 0) or 0))
        old = [c.id for c in expired_chats(list_chats(self.chats_dir()), days, time.time())]
        return delete_chats(self.vault, self.chats_dir(), [c for c in old if c != self.chat_id])

    # ---- attachments ---------------------------------------------------------------------

    def link_name(self, path: str) -> str:
        """How ``path`` is written in a ``[[link]]`` ("" without a path)."""
        return wikilink_to(path, "", set(self.vault.walk_notes())) if path else ""

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
        known = set(self.vault.walk_notes())
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
        quotes = [SavedQuote(p.label, p.kind, p.size(), p.text, p.note) for p in selections]
        turn = SavedTurn("user", text, label, quotes=quotes)
        self.turns.append(turn)
        return Outgoing(turn, attached, names)

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
        return build_context(
            self.vault,
            current_path=snap.path,
            current_text=snap.text,
            selection=attached or snap.selection,
            mentions=[*extract_mentions(question), *notes],
            open_tabs=snap.tabs,
            include_tabs=include_tabs,
            index=self.index,
            budget=budget if budget is not None else self.budget(),
        )

    def system_prompt(self, context: Context) -> str:
        return context.system_prompt(
            self._user_name(), self.language(), system_instruction(self.config, self.vault.root)
        )

    def chat_messages(
        self, context: Context, question: str, room: int | None = None
    ) -> list[ChatMessage]:
        """The messages for the newest question: the system prompt, the earlier turns and the
        question. Earlier turns are taken newest first while they fit in ``room`` tokens (all
        of the prompt; None = no limit), at most ``ai.history_turns``; failed and empty ones
        are left out."""
        system = ChatMessage("system", self.system_prompt(context))
        ask = ChatMessage("user", question)
        keep = int(str(self.setting("ai.history_turns", HISTORY_TURNS)))
        left = None if room is None else room - message_tokens([system, ask])
        past: list[ChatMessage] = []
        for turn in reversed(self.turns[:-2]):
            if len(past) >= keep:
                break
            if turn.error or not turn.text.strip():
                continue
            msg = ChatMessage("user" if turn.role == "user" else "assistant", turn.text)
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
    ) -> AsyncIterator[str]:
        """Answer ``out``: the reply's text grows as the pieces arrive (also yielded)."""
        question = out.turn.text
        window = await self.window()
        room = window - self.answer_room(window)
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
        async for piece in self.stream(messages, window):
            reply.text += piece
            yield piece

    @staticmethod
    def stopped(reply: SavedTurn) -> None:
        reply.text = (reply.text + "\n\n*(stopped)*").strip()

    @staticmethod
    def failed(reply: SavedTurn, message: str) -> None:
        reply.error, reply.text = True, message

    # ---- the provider --------------------------------------------------------------------

    async def stream(
        self, messages: Sequence[ChatMessage], window: int | None = None
    ) -> AsyncIterator[str]:
        """The model's answer to ``messages``, with the chosen model, the options and the
        context window (``window``, else :meth:`window`)."""
        size = window or await self.window()
        options = replace(generation_options(self.config), num_ctx=size)
        async for piece in self.provider.chat(messages, model=self.model(), options=options):
            yield piece

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
        """The messages for an AI command run in note ``path`` (``text``, caret at ``caret``)."""
        source = spec.source if spec.source != "auto" else ("selection" if selected else "note")
        part = {"selection": selected, "before": text[max(0, caret - BEFORE_CARET_CHARS) : caret]}
        given = part.get(source, "")
        context = build_context(
            self.vault,
            current_path=path,
            current_text=text,
            selection=selected if source == "selection" else "",
            index=self.index,
            budget=await self.context_budget(),
        )
        task = question or spec.instruction
        rules = "" if spec.ask else NOTE_ONLY
        return [
            ChatMessage("system", self.system_prompt(context) + rules),
            ChatMessage("user", task + (f"\n\nText:\n{given}" if given else "")),
        ]


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
