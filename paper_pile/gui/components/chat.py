"""Right pane: AI chat (PLAN §4.11).

A model picker, streamed replies rendered as markdown (math and diagrams typeset), Stop, Copy and
*Insert into note* per reply, an ``@`` picker to mention notes, and a switch to include the open
tabs. What the model sees is built by :mod:`paper_pile.core.ai.context`; the provider is
:mod:`paper_pile.core.ai`. If Ollama is not running the pane says so and everything else keeps
working.
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from nicegui import Client, background_tasks, ui

from paper_pile.core.ai.context import Context, EditorSnapshot, build_context, extract_mentions
from paper_pile.core.ai.factory import chat_model, make_provider
from paper_pile.core.ai.provider import (
    ChatMessage,
    Health,
    Provider,
    ProviderError,
    ProviderUnavailableError,
)
from paper_pile.core.config import Config
from paper_pile.core.index import Index
from paper_pile.core.links import wikilink_to
from paper_pile.core.parser import render_html
from paper_pile.core.picker import search_notes
from paper_pile.core.vault import Vault

log = logging.getLogger("paper_pile.chat")

HISTORY_TURNS = 12  # earlier messages sent along with a new one
RENDER_EVERY_S = 0.08  # how often a streaming reply is redrawn
HEALTH_EVERY_S = 30.0
_MENTION_TAIL = re.compile(r"@([^\s@\[\]]*)$")


@dataclass(frozen=True, slots=True)
class Selection:
    """Text selected in the editor, attached to the next message."""

    text: str
    label: str  # "From [[a]]"

    def size(self) -> str:
        lines = len(self.text.strip().splitlines())
        return f"{lines} lines" if lines > 1 else f"{len(self.text.strip())} chars"

    def preview(self, limit: int = 300) -> str:
        t = self.text.strip()
        return t if len(t) <= limit else t[:limit] + "…"


@dataclass(slots=True)
class Turn:
    role: str  # "user" | "assistant"
    text: str
    attachment: str = ""  # the one-line label of an attached selection
    summary: str = ""  # what context an assistant reply was given
    error: bool = False


class ChatPane:
    def __init__(
        self,
        vault: Vault,
        config: Config | None,
        index: Index | None,
        snapshot: Callable[[], Awaitable[EditorSnapshot]],
        insert_text: Callable[[str], None],
        on_health: Callable[[Health], None] = lambda health: None,
        user_name: Callable[[], str] = lambda: "",
        open_paths: Callable[[], list[str]] = lambda: [],
    ) -> None:
        self.vault = vault
        self.config = config
        self.index = index
        self._snapshot = snapshot
        self._insert = insert_text
        self._on_health = on_health
        self._user_name = user_name
        self._open_paths = open_paths
        self.provider: Provider = make_provider(config)
        self.history: list[Turn] = []
        self.health = Health(False, "Checking Ollama…")
        self._task: asyncio.Task[None] | None = None
        self._include_tabs = False
        self._selections: list[Selection] = []
        self.models: list[str] = []
        # widgets
        self._log: ui.column
        self._input: ui.textarea
        self._send: ui.button
        self._banner: ui.row
        self._banner_text: ui.label
        self._model: ui.select
        self._mentions: ui.column
        self._status: ui.label
        self._chips: ui.column
        self._client: Client

    # ---- building ------------------------------------------------------------------------

    def build(self) -> None:
        self._client = ui.context.client
        with ui.column().classes("pp-pane pp-chat"):
            with ui.row().classes("pp-chat-head items-center no-wrap"):
                ui.label("AI chat").classes("pp-pane-title")
                ui.space()
                self._model = (
                    ui.select([], value=None, on_change=lambda e: self._model_changed(e.value))
                    .props("dense borderless options-dense")
                    .classes("pp-chat-model")
                    .tooltip("Model")
                )
            self._banner = ui.row().classes("pp-chat-banner items-center no-wrap")
            with self._banner:
                self._banner_text = ui.label("").classes("pp-chat-banner-text")
                ui.button(
                    "Retry", on_click=lambda: background_tasks.create(self.check_health())
                ).props("flat dense no-caps size=sm")
            self._banner.set_visibility(False)
            self._log = ui.column().classes("pp-chat-log")
            self._render_log()
            with ui.column().classes("pp-chat-compose"):
                self._mentions = ui.column().classes("pp-chat-mentions")
                self._mentions.set_visibility(False)
                with ui.row().classes("pp-chat-options items-center"):
                    ui.switch("Include open tabs", on_change=self._tabs_changed).props(
                        "dense size=xs"
                    )
                    ui.button("Add all tabs", icon="tab", on_click=self.add_all_tabs).props(
                        "flat dense no-caps size=sm"
                    ).tooltip("Mention every open note in the message")
                    self._status = ui.label("").classes("pp-muted pp-chat-ctx")
                self._chips = ui.column().classes("pp-chat-chips")
                self._chips.set_visibility(False)
                with ui.row().classes("items-end no-wrap w-full"):
                    self._input = (
                        ui.textarea(placeholder="Ask about your notes…  (@ to mention a note)")
                        .props("outlined dense autogrow input-style='max-height: 160px'")
                        .classes("pp-chat-input")
                    )
                    self._input.on_value_change(lambda e: self._update_mentions(e.value or ""))
                    self._send = ui.button(icon="send", on_click=self.send_or_stop).props(
                        "flat round dense"
                    )
        ui.on("pp_chat_send", lambda _e: self._enter_pressed())
        ui.on("pp_open_url", lambda e: self._open_url(e.args))
        ui.timer(HEALTH_EVERY_S, lambda: background_tasks.create(self.check_health()))
        background_tasks.create(self.check_health())

    # ---- provider state ------------------------------------------------------------------

    def refresh_names(self) -> None:
        """The profile name changed: show it on the user's messages."""
        self._render_log()

    def reload_provider(self) -> None:
        """The AI settings changed (host / model): build the provider again."""
        self.provider = make_provider(self.config)
        background_tasks.create(self.check_health())

    async def check_health(self) -> None:
        health = await self.provider.health()
        self.health = health
        self.models = list(health.models)
        current = chat_model(self.provider, self.config)
        options = (
            self.models if current in self.models or not self.models else [current, *self.models]
        )
        self._model.set_options(options, value=current if options else None)
        self._banner.set_visibility(not health.ok or bool(health.message))
        self._banner_text.set_text(health.message)
        self._on_health(health)

    def _js(self, code: str) -> None:
        """Run JavaScript on this page (also from background tasks, which have no UI context)."""
        self._client.run_javascript(code)

    def _retry(self) -> None:
        background_tasks.create(self.check_health())

    def _model_changed(self, value: str | None) -> None:
        if not value or self.config is None or value == self.config.get("ai.model"):
            return
        self.config.set("ai.model", value, "global")
        self.config.save("global")

    def _tabs_changed(self, e: object) -> None:
        self._include_tabs = bool(getattr(e, "value", False))

    def _open_url(self, url: object) -> None:
        import webbrowser

        from paper_pile.core.links import external_url

        safe = external_url(str(url))
        if safe:
            webbrowser.open(safe)

    # ---- the message log -----------------------------------------------------------------

    def _render_log(self) -> None:
        self._log.clear()
        with self._log:
            if not self.history:
                ui.label("No messages yet").classes("pp-muted pp-chat-empty")
            for turn in self.history:
                self._bubble(turn)
        self._scroll_down()

    def _bubble(self, turn: Turn) -> ui.html | None:
        if turn.role == "user":
            with ui.column().classes("pp-msg pp-msg-user"):
                ui.label(self._user_name() or "You").classes("pp-msg-who")
                if turn.attachment:
                    ui.label(turn.attachment).classes("pp-muted pp-msg-attach")
                ui.label(turn.text).classes("pp-msg-text")
            return None
        with ui.column().classes("pp-msg pp-msg-ai" + (" pp-msg-error" if turn.error else "")):
            ui.label("Assistant").classes("pp-msg-who")
            body = ui.html(render_html(turn.text), sanitize=False).classes("pp-msg-body")
            if turn.summary:
                ui.label(turn.summary).classes("pp-muted pp-msg-ctx")
            if not turn.error and turn.text.strip():
                with ui.row().classes("pp-msg-actions items-center"):
                    ui.button(
                        icon="content_copy", on_click=lambda t=turn: self._copy(t.text)
                    ).props("flat dense size=xs").tooltip("Copy")
                    ui.button(
                        icon="note_add", on_click=lambda t=turn: self._insert_reply(t.text)
                    ).props("flat dense size=xs").tooltip("Insert into note")
            self._typeset(body)
        return body

    def _typeset(self, body: ui.html) -> None:
        self._js(f"window.ppTypeset && window.ppTypeset(document.getElementById('c{body.id}'))")

    def _scroll_down(self) -> None:
        self._js(f"window.ppChatScroll && window.ppChatScroll('c{self._log.id}')")

    def _copy(self, text: str) -> None:
        self._js(f"navigator.clipboard && navigator.clipboard.writeText({json.dumps(text)})")
        ui.notify("Copied", timeout=1200, position="bottom")

    def _insert_reply(self, text: str) -> None:
        self._insert(text.strip() + "\n")
        ui.notify("Inserted into the note", timeout=1500, position="bottom")

    # ---- adding things to the message ----------------------------------------------------

    def _append(self, text: str) -> None:
        value = self._input.value or ""
        sep = "" if not value or value.endswith(("\n", " ")) else "\n"
        self._input.set_value(value + sep + text)
        self._js(f"document.querySelector('#c{self._input.id} textarea')?.focus()")

    def add_notes(self, paths: list[str]) -> None:
        """Mention notes in the message (``@[[name]]``); ones already mentioned are skipped."""
        known = set(self.vault.walk_notes())
        current = self._input.value or ""
        mentions = []
        for path in paths:
            if path not in known:
                continue
            mention = f"@[[{wikilink_to(path, '', known)}]]"
            if mention not in current and mention not in mentions:
                mentions.append(mention)
        if mentions:
            self._append(" ".join(mentions) + " ")
        else:
            ui.notify("Already in the message", timeout=1200, position="bottom")

    def add_all_tabs(self) -> None:
        paths = self._open_paths()
        if paths:
            self.add_notes(paths)
        else:
            ui.notify("No open notes", timeout=1200, position="bottom")

    def set_selection(self, text: str, path: str) -> None:
        """Attach text selected in the editor. Attachments stay until removed with their cross;
        an empty selection (the user clicked away) changes nothing."""
        if not text.strip():
            return
        name = wikilink_to(path, "", set(self.vault.walk_notes())) if path else ""
        picked = Selection(text, f"From [[{name}]]" if name else "Selected text")
        if picked not in self._selections:
            self._selections.append(picked)
            self._render_selections()

    def _remove_selection(self, picked: Selection) -> None:
        if picked in self._selections:
            self._selections.remove(picked)
            self._render_selections()

    def _render_selections(self) -> None:
        self._chips.clear()
        self._chips.set_visibility(bool(self._selections))
        with self._chips:
            for picked in self._selections:
                with ui.column().classes("pp-chat-chip"):
                    with ui.row().classes("items-center no-wrap w-full"):
                        label = ui.label(f"{picked.label}: [Pasted text · {picked.size()}]")
                        label.classes("pp-chat-chip-text").tooltip("Show or hide the text")
                        ui.button(
                            icon="close",
                            on_click=lambda _e=None, p=picked: self._remove_selection(p),
                        ).props("flat round dense size=xs").tooltip("Remove")
                    body = ui.label(picked.text.strip()).classes("pp-chat-chip-body")
                    body.set_visibility(False)
                    label.on("click", lambda _e=None, b=body: b.set_visibility(not b.visible))

    # ---- @ mentions ----------------------------------------------------------------------

    def _update_mentions(self, value: str) -> None:
        m = _MENTION_TAIL.search(value)
        self._mentions.clear()
        if not m:
            self._mentions.set_visibility(False)
            return
        hits = search_notes(m.group(1), self.vault.walk_notes(), limit=6)
        tail = m.group(0)
        with self._mentions:
            for path in hits:
                label = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                row = ui.row().classes("pp-chat-mention items-baseline no-wrap")
                with row:
                    ui.label(label)
                    folder = path.rpartition("/")[0]
                    if folder:
                        ui.label(folder).classes("pp-muted")
                row.on("click", lambda _e, p=path, t=tail: self._pick_mention(p, t))
        self._mentions.set_visibility(bool(hits))

    def _pick_mention(self, path: str, tail: str) -> None:
        name = wikilink_to(path, "", set(self.vault.walk_notes()))
        value = self._input.value or ""
        self._input.set_value(value[: len(value) - len(tail)] + f"@[[{name}]] ")
        self._mentions.set_visibility(False)

    # ---- sending -------------------------------------------------------------------------

    def _enter_pressed(self) -> None:
        if self._task is None:
            background_tasks.create(self.send())

    async def send_or_stop(self) -> None:
        if self._task is not None:
            self.stop()
        else:
            await self.send()

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def send(self) -> None:
        text = (self._input.value or "").strip()
        if not text or self._task is not None:
            return
        self._input.set_value("")
        self._mentions.set_visibility(False)
        picked, self._selections = self._selections, []
        self._render_selections()
        label = "\n".join(f"{p.label}: [Pasted text]" for p in picked)
        attached = "\n\n".join(f"{p.label}:\n{p.text.strip()}" for p in picked)
        self.history.append(Turn("user", text, label))
        self._task = background_tasks.create(self._answer(text, attached))
        self._send.props("icon=stop")

    async def _answer(self, question: str, attached: str = "") -> None:
        reply = Turn("assistant", "")
        self.history.append(reply)
        self._render_log()
        body = self._last_body()
        try:
            snap = await self._snapshot()
            budget = int(self.config.get("ai.context_budget", 6000)) if self.config else 6000
            context = build_context(
                self.vault,
                current_path=snap.path,
                current_text=snap.text,
                selection=attached or snap.selection,
                mentions=extract_mentions(question),
                open_tabs=snap.tabs,
                include_tabs=self._include_tabs,
                index=self.index,
                budget=budget,
            )
            reply.summary = context.summary()
            self._status.set_text(context.summary())
            await self._stream(reply, body, self._messages(context, question))
        except asyncio.CancelledError:
            reply.text = (reply.text + "\n\n*(stopped)*").strip()
        except ProviderError as exc:
            self._fail(reply, str(exc), unavailable=isinstance(exc, ProviderUnavailableError))
        except Exception:
            log.exception("chat failed")
            self._fail(reply, "Something went wrong; see the log.")
        finally:
            self._task = None
            self._send.props("icon=send")
            self._render_log()

    def _fail(self, reply: Turn, message: str, *, unavailable: bool = False) -> None:
        reply.error, reply.text = True, message
        if unavailable:
            self.health = Health(False, message)
            self._banner.set_visibility(True)
            self._banner_text.set_text(message)
            self._on_health(self.health)

    def _messages(self, context: Context, question: str) -> list[ChatMessage]:
        past = [t for t in self.history[:-2] if not t.error and t.text.strip()][-HISTORY_TURNS:]
        return [
            ChatMessage("system", context.system_prompt(self._user_name())),
            *(ChatMessage("user" if t.role == "user" else "assistant", t.text) for t in past),
            ChatMessage("user", question),
        ]

    def _last_body(self) -> ui.html | None:
        for el in reversed(list(self._log.descendants())):
            if isinstance(el, ui.html):
                return el
        return None

    async def _stream(self, reply: Turn, body: ui.html | None, messages: list[ChatMessage]) -> None:
        last = 0.0
        model = chat_model(self.provider, self.config)
        async for piece in self.provider.chat(messages, model=model):
            reply.text += piece
            now = time.monotonic()
            if body is not None and now - last >= RENDER_EVERY_S:
                last = now
                body.set_content(render_html(reply.text))
                self._scroll_down()
