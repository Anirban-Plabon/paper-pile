"""Right pane: AI chat (PLAN §4.11).

Streamed replies rendered as markdown (math and diagrams typeset), Stop, Copy and *Insert into
note* per reply. The composer is one rounded card: attachment chips (selections, notes, text
files), a ``+`` menu (open tabs, other notes, the editor's selection, upload, include all open
tabs), the input with its ``@`` picker, the model picker and Send. What the model sees is built
by :mod:`paper_pile.core.ai.context`; the provider is :mod:`paper_pile.core.ai`. If Ollama is
not running the pane says so and everything else keeps working.
"""

import asyncio
import html
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from nicegui import Client, background_tasks, ui

from paper_pile.core.ai.attachments import AttachmentError, FileRef, read_text_file
from paper_pile.core.ai.context import (
    Context,
    EditorSnapshot,
    build_context,
    extract_mentions,
    source_view,
)
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
from paper_pile.core.settings import language_name
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
    label: str  # "From [[a]]" (or "Selected text" without a note)
    note: str = ""  # the note it came from, shown in the theme colour
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
        active_path: Callable[[], str | None] = lambda: None,
    ) -> None:
        self.vault = vault
        self.config = config
        self.index = index
        self._snapshot = snapshot
        self._insert = insert_text
        self._on_health = on_health
        self._user_name = user_name
        self._open_paths = open_paths
        self._active_path = active_path
        self.provider: Provider = make_provider(config)
        self.history: list[Turn] = []
        self.health = Health(False, "Checking Ollama…")
        self._task: asyncio.Task[None] | None = None
        self._include_tabs = False
        self._selections: list[Selection] = []
        self._open: Selection | None = None  # the chip whose text is unfolded
        self._notes: list[str] = []  # notes added from the + menu (paths)
        self._files: list[FileRef] = []
        self.models: list[str] = []
        # widgets
        self._log: ui.column
        self._input: ui.textarea
        self._send: ui.button
        self._banner: ui.row
        self._banner_text: ui.label
        self._model: ui.button
        self._model_label: ui.label
        self._model_chev: ui.icon
        self._model_menu: ui.menu
        self._model_names: dict[str, str] = {}  # model -> what the button shows
        self._model_details: dict[str, str] = {}
        self._mentions: ui.column
        self._chips: ui.column
        self._refs: ui.row
        self._strip: ui.row
        self._preview: ui.column
        self._card: ui.column
        self._plus: ui.button
        self._upload: ui.upload
        self._client: Client

    # ---- building ------------------------------------------------------------------------

    def build(self) -> None:
        self._client = ui.context.client
        with ui.column().classes("pp-pane pp-chat"):
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
                with ui.column().classes("pp-chat-card") as card:
                    self._card = card
                    self._strip = ui.row().classes("pp-chat-strip")  # all chips, above a divider
                    self._strip.set_visibility(False)
                    with self._strip:
                        self._refs = ui.row().classes("pp-chat-refs")
                        self._chips = ui.row().classes("pp-chat-chips")
                        self._preview = ui.column().classes("pp-chat-preview")
                    # one line: + | text | model | send (the buttons stay at the bottom as it grows)
                    with ui.row().classes("pp-chat-row items-end no-wrap w-full"):
                        self._plus_button()
                        self._input = (
                            ui.textarea(placeholder="Ask, or @ a note")
                            .props("borderless dense autogrow input-style='max-height: 220px'")
                            .classes("pp-chat-input")
                        )
                        self._input.on_value_change(lambda e: self._input_changed(e.value or ""))
                        self._model_button()
                        self._send = ui.button(
                            icon="fa-solid fa-arrow-up", on_click=self.send_or_stop, color=None
                        )
                        self._send.props("round unelevated dense").classes("pp-chat-send")
                self._upload = ui.upload(
                    on_upload=self._file_uploaded,
                    auto_upload=True,
                    multiple=True,
                    max_file_size=200 * 1024,
                    on_rejected=lambda: ui.notify("Files must be at most 200 KB.", type="warning"),
                ).classes("hidden")
        ui.on("pp_chat_send", lambda _e: self._enter_pressed())
        ui.on("pp_chip_close", lambda _e: self._close_chip())
        ui.on("pp_open_url", lambda e: self._open_url(e.args))
        ui.timer(HEALTH_EVERY_S, lambda: background_tasks.create(self.check_health()))
        background_tasks.create(self.check_health())

    # ---- provider state ------------------------------------------------------------------

    def _language(self) -> str:
        code = str(self.config.get("general.language", "en")) if self.config else "en"
        return language_name(code)

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
        short = {m: m.split(":")[0] for m in options}
        self._model_names = {
            m: (short[m] if list(short.values()).count(short[m]) == 1 else m) for m in options
        }
        self._model_details = dict(health.details)
        self._show_model()
        self._banner.set_visibility(not health.ok or bool(health.message))
        self._banner_text.set_text(health.message)
        self._on_health(health)

    def _js(self, code: str) -> None:
        """Run JavaScript on this page (also from background tasks, which have no UI context)."""
        self._client.run_javascript(code)

    def _retry(self) -> None:
        background_tasks.create(self.check_health())

    # ---- the model menu -------------------------------------------------------------------

    def _model_button(self) -> None:
        self._model = ui.button(color=None).props("flat no-caps dense").classes("pp-chat-model")
        with self._model:
            self._model_label = ui.label("").classes("pp-chat-model-name")
            self._model_chev = ui.icon("fa-solid fa-chevron-down").classes("pp-chat-model-chev")
            self._model_menu = ui.menu().props(
                'anchor="top right" self="bottom right" :offset="[0, 8]"'
            )
            self._model_menu.classes("pp-model-menu")
        self._model_menu.on("before-show", lambda _e: self._build_model_menu())
        for event, icon, open_ in (("show", "up", True), ("hide", "down", False)):
            self._model_menu.on(event, lambda _e, i=icon, o=open_: self._model_open(i, o))
        self._model.tooltip("Model")

    def _model_open(self, chevron: str, is_open: bool) -> None:
        self._model_chev.props(f'name="fa-solid fa-chevron-{chevron}"')
        self._model.classes(
            add="pp-chat-model-open" if is_open else "",
            remove="" if is_open else "pp-chat-model-open",
        )

    def _show_model(self) -> None:
        current = chat_model(self.provider, self.config)
        self._model_label.set_text(self._model_names.get(current, current) or "No model")

    def _build_model_menu(self) -> None:
        current = chat_model(self.provider, self.config)
        self._model_menu.clear()
        with self._model_menu:
            if not self._model_names:
                ui.label("No models installed").classes("pp-model-empty")
            for model, name in self._model_names.items():
                item = ui.item(on_click=lambda m=model: self._model_changed(m))
                with item.classes("pp-model-item"):
                    with ui.column().classes("pp-model-text"):
                        ui.label(name).classes("pp-model-name")
                        # size and family from Ollama; else at least the tag the button hides
                        tag = model.split(":", 1)[1] if ":" in model else ""
                        detail = self._model_details.get(model, "") or tag
                        if detail:
                            ui.label(detail).classes("pp-model-detail")
                    if model == current:
                        ui.icon("fa-solid fa-check").classes("pp-model-check")

    def _model_changed(self, value: str | None) -> None:
        self._model_menu.close()
        if not value or self.config is None or value == self.config.get("ai.model"):
            return
        self.config.set("ai.model", value, "global")
        self.config.save("global")
        self._show_model()

    def _set_include_tabs(self, on: bool) -> None:
        self._include_tabs = on
        self._render_refs()

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
                        icon="fa-regular fa-copy", on_click=lambda t=turn: self._copy(t.text)
                    ).props("flat dense size=xs").tooltip("Copy")
                    ui.button(
                        icon="fa-solid fa-file-circle-plus",
                        on_click=lambda t=turn: self._insert_reply(t.text),
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

    def add_notes(self, paths: list[str]) -> None:
        """Attach notes as chips; their text goes to the model with the next message."""
        known = set(self.vault.walk_notes())
        added = [p for p in paths if p in known and p not in self._notes]
        if added:
            self._notes.extend(added)
            self._render_refs()
        else:
            ui.notify("Already attached", timeout=1200, position="bottom")

    def _remove_note(self, path: str) -> None:
        if path in self._notes:
            self._notes.remove(path)
            self._render_refs()

    async def _file_uploaded(self, e: object) -> None:
        file = getattr(e, "file", None)
        if file is None:
            return
        try:
            ref = read_text_file(file.name, await file.read())
        except AttachmentError as exc:
            ui.notify(str(exc), type="warning")
            return
        if ref not in self._files:
            self._files.append(ref)
            self._render_refs()

    def _remove_file(self, ref: FileRef) -> None:
        if ref in self._files:
            self._files.remove(ref)
            self._render_refs()

    def _render_refs(self) -> None:
        """Chips for notes, files and the include-all-tabs switch (selections have their own)."""
        self._refs.clear()
        self._sync_strip()
        with self._refs:
            if self._include_tabs:
                n = len(self._open_paths())
                self._ref_chip("tab", f"All open tabs ({n})", lambda: self._set_include_tabs(False))
            for path in self._notes:
                name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                self._ref_chip("description", name, lambda p=path: self._remove_note(p), path)
            for ref in self._files:
                label = f"{ref.name} · {ref.size()}"
                self._ref_chip("attach_file", label, lambda r=ref: self._remove_file(r))

    def _sync_strip(self) -> None:
        """The chip strip (and the divider under it) shows only while something is attached."""
        self._strip.set_visibility(
            bool(self._selections or self._notes or self._files or self._include_tabs)
        )

    def _ref_chip(self, icon: str, label: str, remove: Callable[[], None], tip: str = "") -> None:
        row = ui.row().classes("pp-chat-ref items-center no-wrap")
        with row:
            ui.icon(icon).classes("pp-chat-ref-icon")
            ui.label(label).classes("pp-chat-ref-text" + (" pp-chat-ref-note" if tip else ""))
            ui.button(icon="fa-solid fa-xmark", on_click=lambda _e=None: remove()).props(
                "flat round dense size=xs"
            ).tooltip("Remove")
        if tip:
            row.tooltip(tip)

    # ---- the + menu ----------------------------------------------------------------------

    def _plus_button(self) -> None:
        self._plus = ui.button(icon="fa-solid fa-plus", color=None).props(
            "round flat dense aria-label='Add context'"
        )
        self._plus.classes("pp-chat-plus")
        with self._plus:
            # anchored to the whole card, so it opens above the text and not over it
            menu = ui.menu().props(
                f'no-parent-event target="#c{self._card.id}" anchor="top left" '
                'self="bottom left" :offset="[0, 8]"'
            )
            menu.classes("pp-chat-menu")
        self._plus.on_click(menu.toggle)  # only a click on the button opens it, never the card
        menu.on("before-show", lambda _e: self._build_menu(menu))
        menu.on("show", lambda _e: self._plus.props('icon="fa-solid fa-xmark"'))
        menu.on("hide", lambda _e: self._plus.props('icon="fa-solid fa-plus"'))

    def _build_menu(self, menu: ui.menu) -> None:
        menu.clear()
        active = self._active_path()
        paths = self._open_paths()
        with menu:
            for path in paths:
                title = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                with ui.menu_item(on_click=lambda _e=None, p=path: self.add_notes([p])):
                    ui.icon("fa-regular fa-file-lines").classes("pp-menu-icon")
                    ui.label(title).classes("pp-menu-title")
                    if path == active:
                        ui.icon("fa-regular fa-circle-check").classes("pp-menu-check")
            with ui.menu_item(auto_close=False):
                ui.icon("fa-solid fa-ellipsis").classes("pp-menu-icon")
                ui.label("Add more notes").classes("pp-menu-title")
                ui.icon("fa-solid fa-chevron-right").classes("pp-menu-check")
                self._more_notes_menu(menu)
            ui.separator()
            with ui.menu_item(
                on_click=lambda _e=None: background_tasks.create(self._from_screen())
            ):
                ui.icon("fa-regular fa-square").classes("pp-menu-icon")
                ui.label("Select from screen").classes("pp-menu-title")
            with ui.menu_item(on_click=lambda _e=None: self._upload.run_method("pickFiles")):
                ui.icon("fa-solid fa-paperclip").classes("pp-menu-icon")
                ui.label("Upload files").classes("pp-menu-title")
            ui.separator()
            with ui.menu_item(auto_close=False):
                ui.icon("fa-regular fa-window-restore").classes("pp-menu-icon")
                ui.label("Include open tabs").classes("pp-menu-title")
                ui.switch(
                    value=self._include_tabs, on_change=lambda e: self._set_include_tabs(e.value)
                ).props("dense")

    def _more_notes_menu(self, root: ui.menu) -> None:
        with ui.menu().props('anchor="top end" self="top start"').classes("pp-chat-menu"):
            results = ui.column().classes("pp-chat-more")

            def pick(path: str) -> None:
                self.add_notes([path])
                root.close()

            def fill(query: str) -> None:
                results.clear()
                with results:
                    for path in search_notes(query, self.vault.walk_notes(), limit=8):
                        title = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                        with ui.menu_item(on_click=lambda _e=None, p=path: pick(p)):
                            ui.label(title).classes("pp-menu-title")
                            folder = path.rpartition("/")[0]
                            if folder:
                                ui.label(folder).classes("pp-muted")

            ui.input(placeholder="Search notes", on_change=lambda e: fill(e.value or "")).props(
                "dense borderless autofocus"
            ).classes("pp-chat-more-search")
            fill("")

    def _spawn(self, coro: Awaitable[None]) -> None:
        background_tasks.create(coro)

    async def _from_screen(self) -> None:
        """Attach what is selected in the note, or tell the user to select something."""
        snap = await self._snapshot()
        if snap.selection.strip():
            self.set_selection(snap.selection, snap.path or "")
            return
        with self._client:  # a background task has no UI context of its own
            ui.notify("Select text in a note: it is attached automatically", timeout=2500)
        self._js("document.querySelector('.cm-content')?.focus()")

    def set_selection(self, text: str, path: str) -> None:
        """Attach text selected in the editor. Attachments stay until removed with their cross;
        an empty selection (the user clicked away) changes nothing."""
        if not text.strip():
            return
        name = wikilink_to(path, "", set(self.vault.walk_notes())) if path else ""
        picked = Selection(text, f"From [[{name}]]" if name else "Selected text", name)
        if picked not in self._selections:
            self._selections.append(picked)
            self._render_selections()

    def set_block(self, kind: str, lang: str, text: str, path: str) -> None:
        """Attach a code / math / diagram block (its copy button) like a selection."""
        body = text.strip("\n")
        if kind == "math":
            fenced, label = f"$$\n{body}\n$$", "Math block"
        elif kind == "diagram":
            fenced, label = f"```mermaid\n{body}\n```", "Diagram"
        else:
            fenced, label = f"```{lang}\n{body}\n```", "Code block"
        n = len(body.splitlines()) or 1
        name = wikilink_to(path, "", set(self.vault.walk_notes())) if path else ""
        picked = Selection(
            fenced,
            f"From [[{name}]]" if name else label,
            name,
            label,
            f"{n} line{'s' if n != 1 else ''}",
        )
        if picked not in self._selections:
            self._selections.append(picked)
            self._render_selections()

    def _remove_selection(self, picked: Selection) -> None:
        if picked in self._selections:
            self._selections.remove(picked)
            if picked is self._open:
                self._open = None
            self._render_selections()

    def _render_selections(self) -> None:
        self._chips.clear()
        self._preview.clear()
        self._preview.set_visibility(self._open is not None)
        self._sync_strip()
        with self._chips:
            for picked in self._selections:
                row = ui.row().classes("pp-chat-ref pp-chat-chip items-center no-wrap")
                if picked is self._open:
                    row.classes("pp-chat-chip-open")
                with row:
                    ui.icon("fa-solid fa-quote-left").classes("pp-chat-ref-icon")
                    text = f"[{picked.kind} · {picked.size()}]"
                    if picked.note:
                        note = html.escape(picked.note)
                        text = f'From <span class="pp-chat-ref-note">{note}</span>: {text}'
                    label = ui.html(text, sanitize=False)
                    label.classes("pp-chat-ref-text pp-chat-chip-text")
                    label.tooltip("Show or hide the text")
                    label.on("click", lambda _e=None, s=picked: self._toggle_chip(s))
                    ui.button(
                        icon="fa-solid fa-xmark",
                        on_click=lambda _e=None, p=picked: self._remove_selection(p),
                    ).props("flat round dense size=xs").tooltip("Remove")
        if self._open is not None:  # the unfolded text sits under all the chips, above the divider
            with self._preview:
                body = ui.html(render_html(source_view(self._open.text.strip())), sanitize=False)
                body.classes("pp-msg-body pp-chat-chip-body")
                self._typeset(body)

    def _toggle_chip(self, picked: Selection) -> None:
        """Only one chip is unfolded at a time; clicking it again (or elsewhere) folds it."""
        self._open = None if picked is self._open else picked
        self._render_selections()

    def _close_chip(self) -> None:
        if self._open is not None:
            self._open = None
            self._render_selections()

    # ---- @ mentions ----------------------------------------------------------------------

    def _input_changed(self, value: str) -> None:
        self._send.classes(
            add="pp-chat-send-ready" if value.strip() else "",
            remove="" if value.strip() else "pp-chat-send-ready",
        )
        if not value:  # cleared (sent): back to one line; typing is handled in chat.js
            ui.run_javascript(
                f"document.getElementById('c{self._card.id}')?.classList.remove('pp-chat-multi')"
            )
        self._update_mentions(value)

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
        picked, self._selections, self._open = self._selections, [], None
        notes, self._notes = self._notes, []
        files, self._files = self._files, []
        self._render_selections()
        self._render_refs()
        known = set(self.vault.walk_notes())
        names = [wikilink_to(p, "", known) for p in notes if p in known]
        label = "\n".join(
            [f"{p.label}: [{p.kind}]" for p in picked]
            + [f"[[{n}]]" for n in names]
            + [f"{f.name}: [File]" for f in files]
        )
        attached = "\n\n".join(
            [f"{p.label}:\n{p.text.strip()}" for p in picked]
            + [f"File {f.name}:\n{f.text.strip()}" for f in files]
        )
        self.history.append(Turn("user", text, label))
        self._task = background_tasks.create(self._answer(text, attached, names))
        self._send.props('icon="fa-solid fa-stop"')

    async def _answer(
        self, question: str, attached: str = "", notes: list[str] | None = None
    ) -> None:
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
                mentions=[*extract_mentions(question), *(notes or [])],
                open_tabs=snap.tabs,
                include_tabs=self._include_tabs,
                index=self.index,
                budget=budget,
            )
            reply.summary = context.summary()
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
            self._send.props('icon="fa-solid fa-arrow-up"')
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
            ChatMessage("system", context.system_prompt(self._user_name(), self._language())),
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
