"""Right pane: AI chat (PLAN §4.11).

Streamed replies rendered as markdown (math and diagrams typeset), Stop, Copy and *Insert into
note* per reply. The composer is one rounded card: attachment chips (selections, notes, text
files), a ``+`` menu (open tabs, other notes, the editor's selection, upload, include all open
tabs), the input with its ``@`` picker, the model picker and Send. What the model sees is built
by the AI engine (:mod:`paper_pile.core.ai.engine`), which also keeps the open chat; this pane
only draws. If Ollama is not running the pane says so and everything else keeps working.

A header row shows the chat's title; its ⋮ button opens the chat menu: New chat, the latest
saved chats (*Memories*, one line each; older ones under *More chats*) and *AI settings*. Chats
are saved per vault (:mod:`paper_pile.core.ai.chats`) after every message (unless turned off);
Settings → AI → Memories browses, reads and deletes them.
"""

import asyncio
import html
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable

from nicegui import Client, background_tasks, ui

from paper_pile.core.ai.attachments import AttachmentError, FileRef, read_text_file
from paper_pile.core.ai.chats import SavedChat, SavedQuote, list_chats
from paper_pile.core.ai.chats import SavedTurn as Turn
from paper_pile.core.ai.context import EditorSnapshot, source_view
from paper_pile.core.ai.engine import AiEngine, Outgoing, Selection
from paper_pile.core.ai.provider import Health, ProviderError, ProviderUnavailableError
from paper_pile.core.links import wikilink_to
from paper_pile.core.parser import render_html
from paper_pile.core.picker import search_notes
from paper_pile.gui.icons import ico, icon_button, line_icon, set_icon
from paper_pile.gui.tips import tip

THINKING_HTML = '<span class="pp-thinking" aria-label="Thinking"><i></i><i></i><i></i></span>'
log = logging.getLogger("paper_pile.chat")

RENDER_EVERY_S = 0.08  # how often a streaming reply is redrawn
HEALTH_EVERY_S = 30.0
RECENT_CHATS = 5  # shown in the ⋮ menu; older ones under "More chats"
_MENTION_TAIL = re.compile(r"@([^\s@\[\]]*)$")


def _chip_text(note: str, kind: str, size: str) -> str:
    """An attached selection's chip: ``From <note>: [Selected text · 3 lines]`` (HTML)."""
    text = html.escape(f"[{kind} · {size}]")
    if not note:
        return text
    return f'From <span class="pp-chat-ref-note">{html.escape(note)}</span>: {text}'


class ChatPane:
    def __init__(
        self,
        ai: AiEngine,
        snapshot: Callable[[], Awaitable[EditorSnapshot]],
        insert_text: Callable[[str], None],
        on_health: Callable[[Health], None] = lambda health: None,
        user_name: Callable[[], str] = lambda: "",
        open_paths: Callable[[], list[str]] = lambda: [],
        active_path: Callable[[], str | None] = lambda: None,
        open_settings: Callable[[], None] = lambda: None,
        enabled: Callable[[], bool] = lambda: True,  # the AI feature switch
    ) -> None:
        self.ai = ai
        self.vault = ai.vault
        self.config = ai.config
        self._enabled = enabled
        self._snapshot = snapshot
        self._insert = insert_text
        self._on_health = on_health
        self._user_name = user_name
        self._open_paths = open_paths
        self._active_path = active_path
        self._open_settings = open_settings
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
        self._title: ui.label
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
            with ui.row().classes("pp-chat-head items-center no-wrap"):
                self._title = ui.label("").classes("pp-chat-title")
                self._menu_button()
            self._banner = ui.row().classes("pp-chat-banner items-center no-wrap")
            with self._banner:
                self._banner_text = ui.label("").classes("pp-chat-banner-text")
                ui.button(
                    "Retry", on_click=lambda: background_tasks.create(self.check_health())
                ).props("flat dense no-caps size=sm")
            self._banner.set_visibility(False)
            with ui.element("div").classes("pp-chat-logwrap"):
                self._log = ui.column().classes("pp-chat-log")
                self._render_log()
                self._jump_buttons()
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
                            icon=ico("arrow-up"), on_click=self.send_or_stop, color=None
                        )
                        self._send.props("round unelevated dense").classes("pp-chat-send")
                ui.label("AI can make mistakes. Check important information.").classes(
                    "pp-chat-disclaimer"
                )
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
        self.prune_chats()

    # ---- provider state ------------------------------------------------------------------

    def refresh_names(self) -> None:
        """The profile name changed: show it on the user's messages."""
        self._render_log()

    def prune_chats(self) -> None:
        """Move chats older than ``ai.keep_chats_days`` to the trash (never the open one)."""
        moved = self.ai.prune()
        if moved:
            log.info("moved %d old chats to the trash", moved)

    def reload_provider(self) -> None:
        """The AI settings changed (host / model): build the provider again."""
        self.ai.reload()
        background_tasks.create(self.check_health())

    async def check_health(self) -> None:
        if not self._enabled():  # AI is switched off: never talk to Ollama
            return
        health = await self.ai.health()
        self.health = health
        self.models = list(health.models)
        current = self.ai.model()
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
            self._model_chev = line_icon("chevron-down", "s").classes("pp-chat-model-chev")
            self._model_menu = ui.menu().props(
                'anchor="top right" self="bottom right" :offset="[0, 8]"'
            )
            self._model_menu.classes("pp-model-menu")
        self._model_menu.on("before-show", lambda _e: self._build_model_menu())
        for event, open_ in (("show", True), ("hide", False)):
            self._model_menu.on(event, lambda _e, o=open_: self._model_open(o))

    def _model_open(self, is_open: bool) -> None:
        self._model.classes(  # the chevron turns by CSS
            add="pp-chat-model-open" if is_open else "",
            remove="" if is_open else "pp-chat-model-open",
        )

    def _show_model(self) -> None:
        current = self.ai.model()
        self._model_label.set_text(self._model_names.get(current, current) or "No model")

    def _build_model_menu(self) -> None:
        current = self.ai.model()
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
                        line_icon("check", "s").classes("pp-model-check pp-check")

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

    # ---- the ⋮ menu: new chat, saved chats, AI settings ----------------------------------

    def _menu_button(self) -> None:
        button = icon_button("ellipsis-vertical", lambda: None, "Chats and settings")
        button.classes("pp-chat-more-btn")
        with button:
            menu = ui.menu().props('anchor="bottom right" self="top right" :offset="[0, 6]"')
            menu.classes("pp-chat-menu")
        menu.on("before-show", lambda _e: self._build_chat_menu(menu))

    def _build_chat_menu(self, menu: ui.menu) -> None:
        busy = self._task is not None  # no switching while a reply streams in
        chats = list_chats(self.ai.chats_dir())
        menu.clear()
        with menu:
            with ui.menu_item(on_click=lambda _e=None: self.new_chat()) as item:
                line_icon("square-pen").classes("pp-menu-icon")
                ui.label("New chat").classes("pp-menu-title")
            if busy or not self.ai.turns:
                item.props("disable")
            ui.separator()
            ui.label("Memories").classes("pp-menu-caption")
            if not chats:
                ui.label("No saved chats yet").classes("pp-muted pp-menu-empty")
            for chat in chats[:RECENT_CHATS]:
                self._chat_item(chat, menu, busy)
            if len(chats) > RECENT_CHATS:
                with ui.menu_item(auto_close=False):
                    line_icon("history").classes("pp-menu-icon")
                    ui.label(f"More chats ({len(chats) - RECENT_CHATS})").classes("pp-menu-title")
                    line_icon("chevron-right", "s").classes("pp-menu-check")
                    self._more_chats_menu(chats[RECENT_CHATS:], menu, busy)
            ui.separator()
            with ui.menu_item(on_click=lambda _e=None: self._open_settings()):
                line_icon("settings").classes("pp-menu-icon")
                ui.label("AI settings").classes("pp-menu-title")

    def _chat_item(self, chat: SavedChat, root: ui.menu, busy: bool) -> None:
        item = ui.menu_item(on_click=lambda _e=None, c=chat.id: self.open_chat(c))
        item.classes("pp-chat-saved")
        if busy:
            item.props("disable")
        with item:
            ui.label(chat.title or "Untitled chat").classes("pp-menu-title")
            if chat.id == self.ai.chat_id:
                line_icon("check", "s").classes("pp-menu-check pp-check")
            remove = line_icon("trash-2", "s").classes("pp-chat-saved-del")
            tip(remove, "Delete chat")
            remove.props("tabindex=0 role=button aria-label='Delete chat'")  # reachable by Tab
            remove.on("click.stop", lambda _e, c=chat.id: self._delete_chat(c, root))
            remove.on("keydown.enter.stop", lambda _e, c=chat.id: self._delete_chat(c, root))

    def _more_chats_menu(self, chats: list[SavedChat], root: ui.menu, busy: bool) -> None:
        with ui.menu().props('anchor="top end" self="top start"').classes("pp-chat-menu"):
            results = ui.column().classes("pp-chat-more")

            def fill(query: str) -> None:
                words = query.lower().split()
                results.clear()
                with results:
                    for chat in chats:
                        if all(w in chat.title.lower() for w in words):
                            self._chat_item(chat, root, busy)

            ui.input(placeholder="Search chats", on_change=lambda e: fill(e.value or "")).props(
                "dense borderless autofocus"
            ).classes("pp-chat-more-search")
            fill("")

    def new_chat(self) -> None:
        """Start an empty chat (the current one is saved after every message)."""
        if self._task is not None:
            return
        self.ai.new_chat()
        self._render_log()

    def open_chat(self, chat_id: str) -> bool:
        """Show a saved chat; False while a reply streams in (or when it cannot be read)."""
        if self._task is not None:
            return False
        if chat_id == self.ai.chat_id:
            return True
        if not self.ai.open_chat(chat_id):
            ui.notify("That chat could not be read.", type="warning")
            return False
        self._render_log()
        return True

    @property
    def chat_id(self) -> str:
        return self.ai.chat_id

    def chats_deleted(self, chat_ids: set[str]) -> None:
        """Settings moved chats to the trash: start afresh if the open one was among them."""
        if self._task is None and self.ai.forget(*chat_ids):
            self._render_log()

    def _delete_chat(self, chat_id: str, root: ui.menu) -> None:
        root.close()
        try:
            was_open = self.ai.delete_chat(chat_id)
        except OSError:
            log.exception("could not delete chat %s", chat_id)
            ui.notify("Could not delete the chat.", type="negative")
            return
        if was_open:
            self._render_log()
        ui.notify("Chat moved to the trash", timeout=1500, position="bottom")

    # ---- the message log -----------------------------------------------------------------

    def _render_log(self) -> None:
        self._title.set_text(self.ai.title or "New chat")
        self._log.clear()
        with self._log:
            if not self.ai.turns:
                ui.label("No messages yet").classes("pp-muted pp-chat-empty")
            for i, turn in enumerate(self.ai.turns):
                self._bubble(turn)
                if i == self.ai.summarized - 1:  # the model gets a summary of what is above
                    ui.label("Earlier messages summarized").classes("pp-muted pp-chat-compacted")
        self._scroll_down()

    def _bubble(self, turn: Turn) -> ui.html | None:
        if turn.role == "user":
            with ui.column().classes("pp-msg pp-msg-user"):
                ui.label(self._user_name() or "You").classes("pp-msg-who")
                for quote in turn.quotes:
                    self._quote_chip(quote)
                rest = "\n".join(turn.attachment.splitlines()[len(turn.quotes) :])
                if rest:  # notes and files (the quotes' lines come first)
                    ui.label(rest).classes("pp-muted pp-msg-attach")
                ui.label(turn.text).classes("pp-msg-text")
            return None
        with ui.column().classes("pp-msg pp-msg-ai" + (" pp-msg-error" if turn.error else "")):
            ui.label("Assistant").classes("pp-msg-who")
            waiting = not turn.text and not turn.error and self._task is not None
            if waiting and self.ai.turns and turn is self.ai.turns[-1]:  # until the first words
                content = (
                    '<span class="pp-thinking" aria-label="Thinking"><i></i><i></i><i></i></span>'
                )
            else:
                content = render_html(turn.text)
            body = ui.html(content, sanitize=False).classes("pp-msg-body")
            if turn.summary:
                ui.label(turn.summary).classes("pp-muted pp-msg-ctx")
            if not turn.error and turn.text.strip():
                with ui.row().classes("pp-msg-actions items-center"):
                    ui.button(icon=ico("copy"), on_click=lambda t=turn: self._copy(t.text)).props(
                        "flat dense size=xs"
                    ).props('data-tip="Copy"')
                    ui.button(
                        icon=ico("file-plus"),
                        on_click=lambda t=turn: self._insert_reply(t.text),
                    ).props("flat dense size=xs").props('data-tip="Insert into note"')
            self._typeset(body)
        return body

    def _quote_chip(self, quote: SavedQuote) -> None:
        """A sent selection: the same chip as in the composer; a click unfolds its text."""
        with ui.column().classes("pp-msg-quote"):
            row = ui.row().classes("pp-chat-ref pp-chat-chip items-center no-wrap")
            body = ui.column().classes("pp-msg-quote-body")
            body.set_visibility(False)

            def toggle() -> None:
                if not body.default_slot.children:  # drawn on the first unfold
                    with body:
                        text = render_html(source_view(quote.text.strip()))
                        html_body = ui.html(text, sanitize=False)
                        html_body.classes("pp-msg-body pp-chat-chip-body")
                        self._typeset(html_body)
                body.set_visibility(not body.visible)
                if body.visible:
                    row.classes("pp-chat-chip-open")
                else:
                    row.classes(remove="pp-chat-chip-open")

            with row:
                line_icon("quote").classes("pp-chat-ref-icon")
                label = ui.html(_chip_text(quote.note, quote.kind, quote.size), sanitize=False)
                label.classes("pp-chat-ref-text pp-chat-chip-text")
                label.on("click", toggle)
                tip(label, "Show the attached text")

    def _typeset(self, body: ui.html) -> None:
        self._js(f"window.ppTypeset && window.ppTypeset(document.getElementById('c{body.id}'))")

    def _jump_buttons(self) -> None:
        """Floating to-the-top / to-the-bottom buttons; ``static/chat.js`` shows each only when
        there is somewhere to go and scrolls in the page (no round trip)."""
        log_id = f"c{self._log.id}"
        with ui.column().classes("pp-chat-jumps"):
            for where, icon, label in (
                ("top", "arrow-up-to-line", "Scroll to top"),
                ("bottom", "arrow-down-to-line", "Scroll to bottom"),
            ):
                button = ui.button(icon=ico(icon), color=None).props("round flat dense")
                button.classes(f"pp-fab pp-chat-jump pp-chat-jump-{where}")
                button.on("click", js_handler=f"() => window.ppChatJump('{log_id}', '{where}')")
                tip(button, label)

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
        known = set(self.ai.note_paths())
        added = [p for p in paths if p in known and p not in self._notes]
        if added:
            self._notes.extend(added)
            self._render_refs()
        else:
            ui.notify("Already attached", timeout=1200, position="bottom")

    def ask(self, path: str, prompt: str, *, send: bool) -> None:
        """The note menu's AI items: attach ``path`` and put ``prompt`` in the composer; send it
        right away, or leave it for the user to finish (caret at the end)."""
        if path not in self._notes and path in set(self.ai.note_paths()):
            self._notes.append(path)
            self._render_refs()
        self._input.set_value(prompt)
        if send:
            background_tasks.create(self.send())
            return
        self.focus_input()

    def focus_input(self) -> None:
        """Put the caret at the end of the composer."""
        self._js(
            "const t = document.querySelector('.pp-chat-input textarea');"
            "if (t) { t.focus(); t.setSelectionRange(t.value.length, t.value.length); }"
        )

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
                self._ref_chip(
                    "app-window", f"All open tabs ({n})", lambda: self._set_include_tabs(False)
                )
            for path in self._notes:
                name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                self._ref_chip("file-text", name, lambda p=path: self._remove_note(p), path)
            for ref in self._files:
                label = f"{ref.name} · {ref.size()}"
                self._ref_chip("paperclip", label, lambda r=ref: self._remove_file(r))

    def _sync_strip(self) -> None:
        """The chip strip (and the divider under it) shows only while something is attached."""
        self._strip.set_visibility(
            bool(self._selections or self._notes or self._files or self._include_tabs)
        )

    def _ref_chip(self, icon: str, label: str, remove: Callable[[], None], tip: str = "") -> None:
        row = ui.row().classes("pp-chat-ref items-center no-wrap")
        with row:
            line_icon(icon).classes("pp-chat-ref-icon")
            ui.label(label).classes("pp-chat-ref-text" + (" pp-chat-ref-note" if tip else ""))
            ui.button(icon=ico("x"), on_click=lambda _e=None: remove()).props(
                "flat dense size=xs"
            ).classes("pp-i-s")

    # ---- the + menu ----------------------------------------------------------------------

    def _plus_button(self) -> None:
        self._plus = ui.button(icon=ico("plus"), color=None).props(
            "flat round dense aria-label='Add context'"  # a circle, like the send button
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
        menu.on("show", lambda _e: set_icon(self._plus, "x"))
        menu.on("hide", lambda _e: set_icon(self._plus, "plus"))

    def _build_menu(self, menu: ui.menu) -> None:
        menu.clear()
        active = self._active_path()
        paths = self._open_paths()
        with menu:
            for path in paths:
                title = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                with ui.menu_item(on_click=lambda _e=None, p=path: self.add_notes([p])):
                    line_icon("file-text").classes("pp-menu-icon")
                    ui.label(title).classes("pp-menu-title")
                    if path == active:
                        line_icon("check", "s").classes("pp-menu-check pp-check")
            with ui.menu_item(auto_close=False):
                line_icon("ellipsis").classes("pp-menu-icon")
                ui.label("Add more notes").classes("pp-menu-title")
                line_icon("chevron-right", "s").classes("pp-menu-check")
                self._more_notes_menu(menu)
            ui.separator()
            with ui.menu_item(
                on_click=lambda _e=None: background_tasks.create(self._from_screen())
            ):
                line_icon("text-select").classes("pp-menu-icon")
                ui.label("Select from screen").classes("pp-menu-title")
            with ui.menu_item(on_click=lambda _e=None: self._upload.run_method("pickFiles")):
                line_icon("paperclip").classes("pp-menu-icon")
                ui.label("Upload files").classes("pp-menu-title")
            ui.separator()
            with ui.menu_item(auto_close=False):
                line_icon("app-window").classes("pp-menu-icon")
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
                    for path in search_notes(query, self.ai.note_paths(), limit=8):
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
        picked = self.ai.selection(text, path)
        if picked not in self._selections:
            self._selections.append(picked)
            self._render_selections()

    def set_block(self, kind: str, lang: str, text: str, path: str) -> None:
        """Attach a code / math / diagram block (its copy button) like a selection."""
        picked = self.ai.block(kind, lang, text, path)
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
                    line_icon("quote").classes("pp-chat-ref-icon")
                    text = _chip_text(picked.note, picked.kind, picked.size())
                    label = ui.html(text, sanitize=False)
                    label.classes("pp-chat-ref-text pp-chat-chip-text")
                    label.on("click", lambda _e=None, s=picked: self._toggle_chip(s))
                    ui.button(
                        icon=ico("x"),
                        on_click=lambda _e=None, p=picked: self._remove_selection(p),
                    ).props("flat dense size=xs").classes("pp-i-s")
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
        if (
            not value
        ):  # cleared (sent): fit again (by the placeholder); typing is handled in chat.js
            ui.run_javascript(
                f"(a => a && window.ppChatFit && window.ppChatFit(a))"
                f"(document.querySelector('#c{self._card.id} textarea'))"
            )
        self._update_mentions(value)

    def _update_mentions(self, value: str) -> None:
        m = _MENTION_TAIL.search(value)
        self._mentions.clear()
        if not m:
            self._mentions.set_visibility(False)
            return
        hits = search_notes(m.group(1), self.ai.note_paths(), limit=6)
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
        name = wikilink_to(path, "", set(self.ai.note_paths()))
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
        if text == "/compact":
            self._input.set_value("")
            self._task = background_tasks.create(self._compact())
            return
        self._input.set_value("")
        self._mentions.set_visibility(False)
        picked, self._selections, self._open = self._selections, [], None
        notes, self._notes = self._notes, []
        files, self._files = self._files, []
        self._render_selections()
        self._render_refs()
        out = self.ai.add_message(text, picked, notes, files)
        self.ai.save()
        self._task = background_tasks.create(self._answer(out))
        set_icon(self._send, "square")

    async def _answer(self, out: Outgoing) -> None:
        reply = self.ai.start_reply()
        self._render_log()
        body = self._last_body()
        try:
            snap = await self._snapshot()
            last = 0.0
            async for _piece in self.ai.answer(reply, out, snap, include_tabs=self._include_tabs):
                now = time.monotonic()
                if body is not None and now - last >= RENDER_EVERY_S:
                    last = now
                    body.set_content(render_html(reply.text))
                    self._scroll_down()
        except asyncio.CancelledError:
            self.ai.stopped(reply)
        except ProviderError as exc:
            self._fail(reply, str(exc), unavailable=isinstance(exc, ProviderUnavailableError))
        except Exception:
            log.exception("chat failed")
            self._fail(reply, "Something went wrong; see the log.")
        finally:
            self._task = None
            set_icon(self._send, "arrow-up")
            self._render_log()
            self.ai.save()

    async def _compact(self) -> None:
        """``/compact``: summarize the earlier messages for the model now."""
        set_icon(self._send, "square")
        try:
            done = await self.ai.compact()
        except asyncio.CancelledError:
            done = False
        finally:
            self._task = None
            set_icon(self._send, "arrow-up")
        with self._client:  # a background task has no UI context of its own
            if done:
                self.ai.save()
                self._render_log()
            message = "Earlier messages summarized" if done else "Nothing to summarize yet"
            ui.notify(message, timeout=1800, position="bottom")

    def _fail(self, reply: Turn, message: str, *, unavailable: bool = False) -> None:
        self.ai.failed(reply, message)
        if unavailable:
            self.health = Health(False, message)
            self._banner.set_visibility(True)
            self._banner_text.set_text(message)
            self._on_health(self.health)

    def _last_body(self) -> ui.html | None:
        for el in reversed(list(self._log.descendants())):
            if isinstance(el, ui.html):
                return el
        return None
