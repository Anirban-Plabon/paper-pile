"""Right pane: AI chat (PLAN §4.11).

Streamed replies rendered as markdown (math and diagrams typeset), Stop, Copy and *Insert into
note* (a diff first) per reply. The composer is one rounded card: attachment chips (selections,
notes, text files), a ``+`` menu (open tabs, other notes, the editor's selection, upload, include
all open tabs), the input with its ``@`` picker, the model picker and Send. What the model sees
is built by the AI engine (:mod:`paper_pile.core.ai.engine`), which also keeps the open chat;
this pane only draws. If the AI backend can't be reached the pane says so and everything else
keeps working.

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
from dataclasses import dataclass
from pathlib import Path

from nicegui import Client, background_tasks, ui

from paper_pile.core.ai.access import AccessDeniedError
from paper_pile.core.ai.attachments import AttachmentError, FileRef, read_text_file
from paper_pile.core.ai.chats import (
    SavedChat,
    SavedQuote,
    list_chats,
    token_text,
    took_text,
    turn_time,
)
from paper_pile.core.ai.chats import SavedTurn as Turn
from paper_pile.core.ai.commands import (
    AiCommand,
    ai_command,
    command_name,
    command_target,
    parse_command,
    search_commands,
)
from paper_pile.core.ai.context import EditorSnapshot, source_view
from paper_pile.core.ai.edit_run import Again, EditEnd
from paper_pile.core.ai.engine import (
    PASTE_CHIP_CHARS,
    PASTE_CHIP_LINES,
    PASTED,
    AiEngine,
    Outgoing,
    Selection,
)
from paper_pile.core.ai.options import Option, suggest_options
from paper_pile.core.ai.prompts import load_prompts, prompts_file, selection_kind, suggestions
from paper_pile.core.ai.provider import Health, ProviderError, ProviderUnavailableError
from paper_pile.core.ai.vault.cite import anchor_line, answer_for_note
from paper_pile.core.ai.vault.searches import remove_search, save_search, saved_searches
from paper_pile.core.links import resolve_wikilink, wikilink_to
from paper_pile.core.parser import render_chat_html
from paper_pile.core.picker import switcher_notes
from paper_pile.gui.components.ai_access import confirm_access
from paper_pile.gui.components.options_box import OptionsBox
from paper_pile.gui.icons import ico, icon_button, line_icon, set_icon
from paper_pile.gui.tips import tip
from paper_pile.gui.vault_render import cite_pills

log = logging.getLogger("paper_pile.chat")


def thinking_html(text: str = "Thinking…") -> str:
    """What the AI is doing before its first words: a small pulsing circle, then the word."""
    return (
        '<span class="pp-thinking" role="status"><i class="pp-thinking-dot"></i>'
        f"{html.escape(text)}</span>"
    )


THINKING = thinking_html()


def show_stop(button: ui.button, busy: bool) -> None:
    """The send button of a chat box: a square (Stop, glowing softly) while the AI answers,
    else the arrow."""
    set_icon(button, "square" if busy else "arrow-up")
    button.classes(
        add="pp-chat-send-busy" if busy else "", remove="" if busy else "pp-chat-send-busy"
    )


RENDER_EVERY_S = 0.08  # how often a streaming reply is redrawn
MENTION_NOTES = 8  # notes in the @ list
MENTION_FOLDERS = 6  # the vault's top folders listed above them (more: type their name)
FOLDER_ROWS = 50  # folders and notes listed for @<folder>/ (the list scrolls)
ADD_NOTES = 5  # notes listed in the + menu (recent ones, or the best matches)
LIVE_META_S = 0.2  # how often the size and time under an answer being written count up
HEALTH_EVERY_S = 30.0
RECENT_CHATS = 5  # shown in the ⋮ menu; older ones under "More chats"
_MENTION_TAIL = re.compile(r"@((?:[^\s@\[\]]|\xa0)*)$")
# a mention in a sent message (as ``core.ai.context.extract_mentions`` reads them)
_MENTION_SHOWN = re.compile(r"@\[\[([^\[\]\n]+)\]\]|(?<![\w@])@((?:[^\s@\[\]]|\xa0)+)")
_MENTION_TRAIL = ".,;:!?)"


def mention_html(text: str) -> str:
    """A user message as HTML: each ``@[[note]]`` / ``@note`` / ``@folder/`` shown as ``@note``
    in the accent colour (user 2026-11-06: no ``[[ ]]``); the rest escaped as it is."""
    out: list[str] = []
    last = 0
    for m in _MENTION_SHOWN.finditer(text):
        name = m.group(1) or m.group(2)
        trail = len(name) - len(name.rstrip(_MENTION_TRAIL)) if m.group(2) else 0
        name = name[: len(name) - trail]
        if not name:
            continue
        out += [
            html.escape(text[last : m.start()]),
            f'<span class="pp-at">@{html.escape(name)}</span>',
        ]
        last = m.end() - trail
    out.append(html.escape(text[last:]))
    return "".join(out)


def mention_text(name: str) -> str:
    """How a picked note or folder goes into the box: ``@name``, its spaces as no-break spaces
    (they look the same and keep it one mention: user 2026-11-06, no ``[[ ]]``); ``@[[name]]``
    only when it could not be one (brackets, a line break, a closing ``.`` / ``)`` …)."""
    bare = re.fullmatch(r"[^\n\t@\[\]]+", name) and not name.endswith(tuple(_MENTION_TRAIL))
    return "@" + name.replace(" ", "\xa0") if bare else f"@[[{name}]]"


# a change command run from the chat box: (path, selected text or None for the whole note,
# command id, the user's words, may the AI answer with options, which button started it)
EditInNote = Callable[[str, str | None, str, str, bool, Again, tuple[str, ...]], Awaitable[EditEnd]]
ACTION_LABELS = {"again": "Try again", "anyway": "Add it anyway", "change": "Change request"}


@dataclass(slots=True)
class _CommandCard:
    """An AI command from the chat box's ``/`` list (PLAN §4.28) while it needs the user: its
    options, or how a change ended without a diff. Shown under the messages, never saved."""

    command_id: str
    words: str
    path: str
    selected: str | None  # the attached text it acts on; None: the whole note
    offer: bool = True  # may a change come back as options
    options: tuple[Option, ...] = ()
    options_title: str = ""
    groups: tuple[str, ...] = ()  # of the options ticked for this run (the edit intent)
    message: str = ""
    error: bool = False
    actions: tuple[str, ...] = ()
    busy: bool = False


def _chip_text(note: str, kind: str, size: str) -> str:
    """An attached selection's chip: ``From <note>: [Selected text · 3 lines]`` (HTML); a large
    paste: ``Pasted: [40 lines]``."""
    if kind == PASTED:
        return html.escape(f"{PASTED}: [{size}]")
    text = html.escape(f"[{kind} · {size}]")
    if not note:
        return text
    return f'From <span class="pp-chat-ref-note">{html.escape(note)}</span>: {text}'


class ChatPane:
    def __init__(
        self,
        ai: AiEngine,
        snapshot: Callable[[], Awaitable[EditorSnapshot]],
        insert_text: Callable[[str], Awaitable[None]],  # an answer into the note, as a diff
        on_health: Callable[[Health], None] = lambda health: None,
        user_name: Callable[[], str] = lambda: "",
        open_paths: Callable[[], list[str]] = lambda: [],
        active_path: Callable[[], str | None] = lambda: None,
        recent_paths: Callable[[], list[str]] = lambda: [],  # recently opened notes, newest first
        open_settings: Callable[[], None] = lambda: None,
        enabled: Callable[[], bool] = lambda: True,  # the AI feature switch
        apply_to_note: Callable[[str, str, str], Awaitable[None]] | None = None,
        open_note: Callable[[str], None] = lambda path: None,
        edit_in_note: EditInNote | None = None,
        open_at: Callable[[str, int, int, bool], None] = lambda path, first, last, split: None,
    ) -> None:
        self.ai = ai
        self.vault = ai.vault
        self.config = ai.config
        self._enabled = enabled
        self._apply_to_note = apply_to_note  # (path, old, new): show an answer as a diff there
        self._open_note = open_note  # a source under an answer was clicked
        self._open_at = open_at  # a citation pill: (path, first line, last line, in split view)
        self._edit_in_note = edit_in_note  # a change command from the / list (PLAN §4.28)
        self._command_card: _CommandCard | None = None
        self._answering: _CommandCard | None = None  # the AI asked: the next message answers
        self._snapshot = snapshot
        self._insert = insert_text
        self._on_health = on_health
        self._user_name = user_name
        self._open_paths = open_paths
        self._active_path = active_path
        self._recent_paths = recent_paths
        self._open_settings = open_settings
        self.health = Health(False, "Checking the AI…")
        self._task: asyncio.Task[None] | None = None
        self._answer_started = 0.0  # time.monotonic() when the answer being written was asked
        self._live_stats: ui.label | None = None  # its size and time so far, under it
        self._asking = False  # an Allow / Not now card is waiting in the chat
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
        self._suggest: ui.row
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
                # prompts for what is attached: stacked above the box, over the log (max 3)
                self._suggest = ui.column().classes("pp-chat-suggest")
                self._suggest.set_visibility(False)
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
                        self._input.props(  # chat.js: a paste this big becomes a chip
                            f"data-pp-paste-lines={PASTE_CHIP_LINES} "
                            f"data-pp-paste-chars={PASTE_CHIP_CHARS}"
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
        ui.on("pp_chat_pick", lambda e: self._picked(dict(e.args)))
        ui.on("pp_chip_close", lambda _e: self._close_chip())
        ui.on("pp_chat_paste", lambda e: self.set_pasted(str(dict(e.args).get("text", ""))))
        ui.on("pp_open_url", lambda e: self._open_url(e.args))
        ui.on("pp_cite", lambda e: self._open_cite(dict(e.args)))  # a citation pill (chat.js)
        ui.on("pp_note", lambda e: self._open_named(dict(e.args)))  # a note named in a list
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
        if not self._enabled():  # AI is switched off: never talk to the backend
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
        message = health.message or self.ai.model_problem(health)
        self._banner.set_visibility(not health.ok or bool(message))
        self._banner_text.set_text(message)
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
            # auto-close: a click on a model closes the menu in the page, no round trip; it pops
            # by CSS (pp-pop, --pp-dur), in step with the chevron
            self._model_menu = ui.menu().props(
                'anchor="top right" self="bottom right" :offset="[0, 8]" auto-close '
                "transition-show=none transition-hide=none transition-duration=0"
            )
            self._model_menu.classes("pp-model-menu")
        self._model_menu.on("before-show", lambda _e: self._build_model_menu())
        # the chevron turns as the menu starts to open / close (user 2026-11-09: it lagged the
        # menu by a round trip); a data attribute, since Python rewrites the class list
        button = f"document.getElementById('c{self._model.id}')"
        for event, flag in (("before-show", "1"), ("before-hide", "")):
            self._model_menu.on(
                event,
                js_handler=f"() => {{ const b = {button}; if (b) b.dataset.ppOpen = '{flag}'; }}",
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
                        # what the backend tells (size, family…); else the tag the button hides
                        tag = model.split(":", 1)[1] if ":" in model else ""
                        detail = self._model_details.get(model, "") or tag
                        if detail:
                            ui.label(detail).classes("pp-model-detail")
                    if model == current:
                        line_icon("check", "s").classes("pp-model-check pp-menu-check pp-check")

    def _model_changed(self, value: str | None) -> None:
        if not value or self.config is None or value == self.config.get("ai.model"):
            return
        self.config.set("ai.model", value, "global")
        self.config.save("global")
        self._show_model()
        background_tasks.create(self.check_health())  # the "not installed" line may go

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
            searches = saved_searches(self.vault.root)
            if searches:  # vault questions to ask again (PLAN_vault_agent P30.41)
                ui.separator()
                ui.label("Saved searches").classes("pp-menu-caption")
                for question in searches[:RECENT_CHATS]:
                    self._search_item(question, menu, busy)
            ui.separator()
            with ui.menu_item(on_click=lambda _e=None: self._open_settings()):
                line_icon("settings").classes("pp-menu-icon")
                ui.label("AI settings").classes("pp-menu-title")

    def _search_item(self, question: str, root: ui.menu, busy: bool) -> None:
        """A saved search (P30.41): click asks it again; the bin forgets it (like a saved
        chat's row)."""

        async def run() -> None:
            root.close()
            if self._task is None:
                self._input.set_value(question)
                await self.send()

        def forget() -> None:
            remove_search(self.vault.root, question)
            self._build_chat_menu(root)

        item = ui.menu_item(on_click=run).classes("pp-chat-saved")
        if busy:
            item.props("disable")
        with item:
            line_icon("search").classes("pp-menu-icon")
            tip(ui.label(question).classes("pp-menu-title"), question)
            remove = line_icon("trash-2", "s").classes("pp-chat-saved-del")
            tip(remove, "Forget this search")
            remove.props("tabindex=0 role=button aria-label='Forget this search'")
            remove.on("click.stop", lambda _e: forget())
            remove.on("keydown.enter.stop", lambda _e: forget())

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
        self._command_card = self._answering = None
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
        self._command_card = self._answering = None
        self._render_log()
        return True

    def can_switch(self) -> bool:
        """Another chat may be opened (no answer is streaming in)."""
        return self._task is None

    def show_open_chat(self) -> None:
        """The engine's open chat was replaced (the Ask box's conversation): draw it."""
        self._render_log()

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
            if not self.ai.turns and self._command_card is None:
                ui.label("No messages yet").classes("pp-muted pp-chat-empty")
            for i, turn in enumerate(self.ai.turns):
                self._bubble(turn)
                if i == self.ai.summarized - 1:  # the model gets a summary of what is above
                    ui.label("Earlier messages summarized").classes("pp-muted pp-chat-compacted")
            if self._command_card is not None:
                self._render_card(self._command_card)
        self._scroll_down()

    def _bubble(self, turn: Turn) -> ui.html | None:
        """One message, with one line under it (user 2026-11-06): its buttons, shown on hover,
        and its info, in one size. The user's: a bubble on the right as wide as its text (at
        most most of the pane); under it Copy, Edit (the last one) and its time. An answer:
        the text; under it its info (:meth:`_reply_meta`) and Copy / Insert into note /
        Answer again. The bubbles tell who wrote what (no names)."""
        if turn.role == "user":
            with ui.column().classes("pp-msg pp-msg-user"):
                for quote in turn.quotes:
                    self._quote_chip(quote)
                rest = "\n".join(turn.attachment.splitlines()[len(turn.quotes) :])
                if rest:  # notes and files (the quotes' lines come first)
                    ui.label(rest).classes("pp-muted pp-msg-attach")
                ui.html(mention_html(turn.text), sanitize=False).classes("pp-msg-text")
                with ui.row().classes("pp-msg-foot pp-msg-foot-user items-center no-wrap"):
                    with ui.row().classes("pp-msg-actions items-center no-wrap"):
                        self._msg_button("copy", "Copy", lambda t=turn: self._copy(t.text))
                        if self._task is None and turn is self._last("user"):
                            self._msg_button("pencil", "Edit and send again", self._edit_last)
                    when = turn_time(turn.at, time.time())
                    if when:
                        ui.label(when).classes("pp-muted pp-msg-ctx")
            return None
        with ui.column().classes("pp-msg pp-msg-ai" + (" pp-msg-error" if turn.error else "")):
            if turn.reasoning:  # a thinking model's reasoning, folded away
                with ui.expansion("Reasoning").props("dense").classes("pp-msg-reasoning"):
                    ui.label(turn.reasoning.strip()).classes("pp-muted pp-msg-reasoning-text")
            waiting = not turn.text and not turn.error and self._task is not None
            if waiting and self.ai.turns and turn is self.ai.turns[-1]:  # until the first words
                content = THINKING
            else:
                content = render_chat_html(turn.text)
                if turn.vault.get("cites"):  # the vault agent's citations as pills (§7.1)
                    content = cite_pills(content, turn.vault["cites"], self.ai.turns.index(turn))
            body = ui.html(content, sanitize=False).classes("pp-msg-body")
            if turn.vault:
                self._vault_extras(turn)
            with ui.row().classes("pp-msg-foot items-center"):
                self._reply_meta(turn)
                if not turn.error and turn.text.strip():
                    with ui.row().classes("pp-msg-actions items-center no-wrap"):
                        self._msg_button("copy", "Copy", lambda t=turn: self._copy(t.text))
                        self._into_note_button(turn)
                        if self._task is None and turn is self.ai.turns[-1]:
                            self._msg_button("refresh-cw", "Answer again", self._regenerate)
            self._typeset(body)
        return body

    # ---- the vault agent's answers (PLAN_vault_agent §7) ---------------------------------------

    def _vault_extras(self, turn: Turn) -> None:
        """Under a vault answer: its steps (folded) and, on the newest answer only, its chips
        — what they send is answered by the agent's open question or understood afresh, so
        they are offered only while that is still the conversation's last word."""
        steps = [s for s in turn.vault.get("steps", []) if isinstance(s, str)]
        if steps:
            with ui.expansion(f"{len(steps)} steps").props("dense").classes("pp-vault-steps"):
                for line in steps:
                    ui.label(line).classes("pp-muted pp-vault-step")
        chips = [c for c in turn.vault.get("chips", []) if isinstance(c, dict) and c.get("label")]
        live = self._task is None and bool(self.ai.turns) and turn is self.ai.turns[-1]
        if not chips or not live:
            return
        review = [r for r in turn.vault.get("review", []) if isinstance(r, dict)]
        if turn.vault.get("kind") == "review" and len(review) > 1:
            self._review_list(review)
        with ui.row().classes("pp-vault-chips items-center"):
            for c in chips:
                ui.button(
                    str(c["label"]), on_click=lambda c=c: self._vault_chip(c), color=None
                ).props("flat dense no-caps").classes("pp-vault-chip")

    def _review_list(self, review: list[dict[str, object]]) -> None:
        """A review of changes to several notes (P30.30): one tick per note, all ticked;
        *Apply selected* sends the ticked numbers — the same answer as typing "1, 3"."""
        boxes: list[tuple[int, ui.checkbox]] = []
        with ui.column().classes("pp-vault-review"):
            for row in review:
                n = int(str(row.get("n", 0)))
                label = f"{n}. {row.get('title', '')}" + (" (new note)" if row.get("new") else "")
                boxes.append(
                    (n, ui.checkbox(label, value=True).props("dense").classes("pp-vault-tick"))
                )

            async def apply_ticked() -> None:
                picked = [n for n, box in boxes if box.value]
                if picked and self._task is None:
                    self._input.set_value(", ".join(map(str, picked)))
                    await self.send()

            ui.button("Apply selected", on_click=apply_ticked, color=None).props(
                "flat dense no-caps"
            ).classes("pp-vault-chip pp-vault-apply")

    async def _vault_chip(self, c: dict[str, object]) -> None:
        """A chip: open notes, save the search, or send its text as the next message — the
        same path as typing."""
        saved = c.get("save")
        if isinstance(saved, str):
            if save_search(self.vault.root, saved):
                ui.notify(
                    "Saved — run it again from the chat menu (⋯)", position="bottom", timeout=2500
                )
            return
        paths = c.get("open")
        if isinstance(paths, list):
            for path in paths:
                if isinstance(path, str) and self.vault.exists(path):
                    self._open_note(path)
            return
        text = str(c.get("send") or c.get("label") or "")
        if text and self._task is None:
            self._input.set_value(text)
            await self.send()

    def _open_named(self, args: dict[str, object]) -> None:
        """A note named in a vault answer's list (``pp-note:`` link): open it, in split
        view with Ctrl."""
        path = str(args.get("path") or "")
        if path and self.vault.exists(path):
            self._open_at(path, 0, 0, bool(args.get("split")))
        elif path:
            ui.notify("That note is not there any more.", position="bottom", timeout=2500)

    def _open_cite(self, args: dict[str, object]) -> None:
        """A citation pill was clicked: the note at the cited lines (found again when the note
        changed since), in split view with Ctrl. A note that is gone or private now says so."""
        try:
            turn = self.ai.turns[int(str(args.get("turn")))]
            n = int(str(args.get("n")))
        except (ValueError, IndexError):
            return
        row = next((c for c in turn.vault.get("cites", []) if c.get("n") == n), None)
        if row is None:
            return
        path = str(row.get("path", ""))
        text = self.ai.read_note(path) if path and self.vault.exists(path) else None
        if text is None:
            ui.notify("That note is not available any more.", position="bottom", timeout=2500)
            return
        start = int(row.get("start", 1) or 1)
        end = max(start, int(row.get("end", start) or start))
        line = anchor_line(text, str(row.get("anchor", "")), start)
        if line is None:
            ui.notify("This part changed since the answer.", position="bottom", timeout=2500)
            line, end = start, start  # just the place, no band over text it no longer is
        self._open_at(path, line, line + (end - start), bool(args.get("split")))

    def _msg_button(self, icon: str, label: str, on_click: Callable[[], object]) -> ui.button:
        button = ui.button(icon=ico(icon), on_click=on_click, color=None)
        button.props("flat dense size=xs").props(f'data-tip="{label}"')
        return button

    def _reply_meta(self, turn: Turn) -> None:
        """One line under an answer (user 2026-11-06): "From <notes> · 1.9k toks · 13:53 · 4.2s"
        (its size, when it ended, how long it took). While it is written the size and the time
        so far count up live and the clock time is left out. What was sent along ("Context:
        note · 1.2k / 8k tokens") is the hover text."""
        live = self._task is not None and bool(self.ai.turns) and turn is self.ai.turns[-1]
        if not live and not (turn.sources or turn.tokens or turn.took or turn.at):
            return
        row = ui.row().classes("pp-msg-meta items-center")
        self._draw_meta(row, turn, live)
        if live:  # the sources arrive once the context is built: then the row is drawn again
            drawn = [tuple(turn.sources)]

            def tick() -> None:
                if tuple(turn.sources) != drawn[0]:
                    drawn[0] = tuple(turn.sources)
                    self._draw_meta(row, turn, True)
                elif self._live_stats is not None:
                    self._live_stats.set_text(self._meta_stats(turn, True))

            ui.timer(LIVE_META_S, tick)  # beside the row (drawing the row again clears it)

    def _draw_meta(self, row: ui.row, turn: Turn, live: bool) -> None:
        row.clear()
        sources = turn.sources if not turn.error else []
        with row:
            if sources:
                ui.label("From").classes("pp-muted pp-msg-ctx")
                for path in sources:
                    name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                    source = ui.button(name, on_click=lambda _e=None, p=path: self._open_note(p))
                    source.props("flat dense no-caps").classes("pp-msg-source")
                    tip(source, path)
            stats = ui.label("").classes("pp-muted pp-msg-ctx pp-msg-stats")
            stats.set_text(self._meta_stats(turn, live))
            if turn.summary:
                tip(stats, turn.summary.replace("Context: ", "Sent along: ", 1))
        self._live_stats = stats if live else None

    def _meta_stats(self, turn: Turn, live: bool) -> str:
        """ "1.9k toks · 13:53 · 4.2s"; live: "120 toks · 3.1s" (no clock time yet)."""
        tokens = self.ai.reply_tokens(turn) if live else turn.tokens
        seconds = time.monotonic() - self._answer_started if live else turn.took
        when = "" if live else turn_time(turn.at, time.time())
        bits = [token_text(tokens) if tokens else "", when, took_text(seconds) if seconds else ""]
        text = " · ".join(bit for bit in bits if bit)
        return f"· {text}" if text and turn.sources and not turn.error else text

    def _into_note_button(self, turn: Turn) -> None:
        """*Insert into note*, one button, always a diff first (user 2026-11-06): an answer about
        one attached selection replaces that text in its note; any other goes in at the caret of
        the note on screen. The edit permission decides as for any AI change."""
        target = self.ai.edit_from_reply(turn) if self._apply_to_note else None
        apply_to = self._apply_to_note

        async def insert() -> None:
            if target is not None and apply_to is not None:
                await apply_to(*target)
            elif turn.vault:  # a vault answer: citations as [[links]], no Sources line (P30.48)
                cites = turn.vault.get("cites", [])
                await self._insert_reply(answer_for_note(turn.text, cites, self.ai.link_name))
            else:
                await self._insert_reply(turn.text)

        shown = "replaces the selection; shows the changes first" if target else "shows it first"
        self._msg_button("file-plus", f"Insert into note ({shown})", insert)

    def _quote_chip(self, quote: SavedQuote) -> None:
        """A sent selection: the same chip as in the composer; a click unfolds its text."""
        with ui.column().classes("pp-msg-quote"):
            row = ui.row().classes("pp-chat-ref pp-chat-chip items-center no-wrap")
            body = ui.column().classes("pp-msg-quote-body")
            body.set_visibility(False)

            def toggle() -> None:
                if not body.default_slot.children:  # drawn on the first unfold
                    with body:
                        text = render_chat_html(source_view(quote.text.strip()))
                        html_body = ui.html(text, sanitize=False)
                        html_body.classes("pp-msg-body pp-chat-chip-body")
                        self._typeset(html_body)
                body.set_visibility(not body.visible)
                if body.visible:
                    row.classes("pp-chat-chip-open")
                else:
                    row.classes(remove="pp-chat-chip-open")

            with row:
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

    async def _insert_reply(self, text: str) -> None:
        await self._insert(text.strip())

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
        self._render_suggestions()

    def _render_suggestions(self) -> None:
        """Prompts that fit what is attached (and the user's own), while the box is empty."""
        kinds = [selection_kind(p.kind, p.text) for p in reversed(self._selections)]
        if self._notes or self._files or self._include_tabs:
            kinds.append("note")
        empty = not (self._input.value or "").strip()
        shown = suggestions(kinds, self._own_prompts()) if empty else []
        self._suggest.clear()
        with self._suggest:
            for prompt in shown:
                chip = ui.button(prompt, on_click=lambda _e=None, p=prompt: self._use_prompt(p))
                chip.props("flat dense no-caps").classes("pp-chat-suggestion")
        self._suggest.set_visibility(bool(shown))

    def _own_prompts(self) -> list[str]:
        setting = str(self.ai.setting("ai.prompts_file", "") or "")
        return load_prompts(prompts_file(self.vault.root, setting))

    def _use_prompt(self, prompt: str) -> None:
        """A suggested prompt was picked: it fills the box (sent only with Enter / Send)."""
        self._input.set_value(prompt)
        self.focus_input()

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
        """The ``+`` menu (user 2026-11-06: smaller): a search bar on top, under it 5 notes —
        open and recently opened ones (the note on screen first, ticked) or, while typing, the
        best matches — then Upload, outside files, *Select from screen* (coming soon) and
        *Include open tabs*."""
        menu.clear()
        with menu:
            search = ui.input(placeholder="Search notes")
            search.props("dense borderless autofocus clearable").classes("pp-chat-add-search")
            with search.add_slot("prepend"):  # where the notes' icons are, under it
                line_icon("search").classes("pp-menu-icon")
            results = ui.column().classes("pp-chat-more pp-chat-add-notes")
            search.on_value_change(lambda e: self._fill_notes(results, menu, e.value or ""))
            self._fill_notes(results, menu, "")
            ui.separator()
            with ui.menu_item(on_click=lambda _e=None: self._upload.run_method("pickFiles")):
                line_icon("paperclip").classes("pp-menu-icon")
                ui.label("Upload files").classes("pp-menu-title")
            outside = self.ai.outside_files() if self.ai.has_access() else []
            if outside:
                with ui.menu_item(auto_close=False):
                    line_icon("folder-open").classes("pp-menu-icon")
                    ui.label("Outside files").classes("pp-menu-title")
                    line_icon("chevron-right", "s").classes("pp-menu-check")
                    self._outside_menu(menu, outside)
            with ui.menu_item().props("disable").classes("pp-chat-soon"):
                line_icon("text-select").classes("pp-menu-icon")
                ui.label("Select from screen").classes("pp-menu-title")
                ui.label("Coming soon").classes("pp-chat-soon-badge")
            ui.separator()
            with ui.menu_item(auto_close=False):
                line_icon("app-window").classes("pp-menu-icon")
                ui.label("Include open tabs").classes("pp-menu-title")
                ui.switch(
                    value=self._include_tabs, on_change=lambda e: self._set_include_tabs(e.value)
                ).props("dense")
            ui.label(self.ai.policy().describe()).classes("pp-muted pp-chat-access")

    def _fill_notes(self, results: ui.column, menu: ui.menu, query: str) -> None:
        """The ``+`` menu's notes: :data:`ADD_NOTES` recent ones, or the best matches."""
        active = self._active_path()
        recent = [p for p in (active, *self._open_paths(), *self._recent_paths()) if p]
        paths = switcher_notes(query, self.ai.note_paths(), recent, limit=ADD_NOTES)
        results.clear()
        with results:
            if not paths:
                ui.label("No notes found").classes("pp-muted pp-menu-empty")
            for path in paths:
                title = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                with ui.menu_item(on_click=lambda _e=None, p=path: self.add_notes([p])):
                    line_icon("file-text").classes("pp-menu-icon")
                    ui.label(title).classes("pp-menu-title")
                    if path == active:
                        line_icon("check", "s").classes("pp-menu-check pp-check")

    def _outside_menu(self, root: ui.menu, files: list[Path]) -> None:
        """Files of the outside folders the AI may read (Settings → AI → Access)."""
        with ui.menu().props('anchor="top end" self="top start"').classes("pp-chat-menu"):
            results = ui.column().classes("pp-chat-more")

            def pick(path: Path) -> None:
                ref = self.ai.outside_ref(path)
                root.close()
                if ref is None:
                    ui.notify("That file cannot be read.", type="warning")
                elif ref not in self._files:
                    self._files.append(ref)
                    self._render_refs()

            def fill(query: str) -> None:
                words = query.lower().split()
                results.clear()
                with results:
                    shown = [f for f in files if all(w in str(f).lower() for w in words)][:8]
                    for path in shown:
                        with ui.menu_item(on_click=lambda _e=None, p=path: pick(p)):
                            ui.label(path.name).classes("pp-menu-title")
                            ui.label(str(path.parent)).classes("pp-muted")

            ui.input(placeholder="Search files", on_change=lambda e: fill(e.value or "")).props(
                "dense borderless autofocus"
            ).classes("pp-chat-more-search")
            fill("")

    def _spawn(self, coro: Awaitable[None]) -> None:
        background_tasks.create(coro)

    def set_selection(self, text: str, path: str) -> None:
        """Attach text selected in the editor. Attachments stay until removed with their cross;
        an empty selection (the user clicked away) changes nothing."""
        if not text.strip():
            return
        picked = self.ai.selection(text, path)
        if picked not in self._selections:
            self._selections.append(picked)
            self._render_selections()

    def set_pasted(self, text: str) -> None:
        """A large paste into the box (chat.js): a ``Pasted: [n lines]`` chip, like a selection."""
        if not text.strip():
            return
        picked = self.ai.pasted(text)
        if picked not in self._selections:
            self._selections.append(picked)
            self._render_selections()
        self.focus_input()

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
                shown = render_chat_html(source_view(self._open.text.strip()))
                body = ui.html(shown, sanitize=False)
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
        if bool(value.strip()) == self._suggest.visible:
            self._render_suggestions()  # typing hides the prompts, an empty box shows them

    def _update_mentions(self, value: str) -> None:
        """The list over the box: ``/`` → the AI commands, ``@`` → folders and notes (user
        2026-11-06: like a coding agent's file picker). ``@`` lists the vault's top folders
        first (``a/``), then notes (recent first, the best matches as more is typed);
        ``@a/…`` lists that folder's folders and notes. ↑ / ↓ move, Enter or Tab picks, Esc
        closes (``static/chat.js``). A picked folder only completes the path: left in the
        message, ``@a/b/`` asks the AI to search that folder (:meth:`AiEngine.vault_scopes`;
        the whole vault is ``@vault``)."""
        self._mentions.clear()
        if re.fullmatch(r"/\S*", value):  # the AI commands (PLAN §4.28)
            self._update_commands(value[1:])
            return
        m = _MENTION_TAIL.search(value)
        if not m:
            self._mentions.set_visibility(False)
            return
        query, tail = m.group(1), m.group(0)
        rows = self._folder_rows(query)  # (kind, id, icon, title, muted)
        if "/" not in query:
            rows = [r for r in rows if r[0] == "folder"][:MENTION_FOLDERS]
            active = self._active_path()
            recent = [p for p in (active, *self._open_paths(), *self._recent_paths()) if p]
            notes = switcher_notes(query, self.ai.note_paths(), recent, limit=MENTION_NOTES)
            rows += [self._note_row(path) for path in notes]
        with self._mentions:
            if not rows:
                ui.label(f"Nothing matches “{query}”").classes("pp-muted pp-chat-pick-none")
            for i, (kind, ident, icon, title, muted) in enumerate(rows):
                row = ui.row().classes(
                    "pp-chat-mention pp-chat-pick items-center no-wrap"
                    + (" pp-chat-pick-active" if i == 0 else "")
                )
                row.props(f'data-kind="{kind}" data-id="{html.escape(ident, quote=True)}"')
                with row:
                    line_icon(icon).classes("pp-menu-icon")
                    ui.label(title).classes("pp-menu-title")
                    if muted:
                        ui.label(muted).classes("pp-muted pp-chat-pick-folder")
                row.on(
                    "mousedown.prevent",
                    lambda _e, k=kind, d=ident, t=tail: self._pick_row(k, d, t),
                )
        self._mentions.set_visibility(True)

    @staticmethod
    def _note_row(path: str) -> tuple[str, str, str, str, str]:
        title = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        return ("note", path, "file-text", title, path.rpartition("/")[0])

    def _folder_rows(self, rest: str) -> list[tuple[str, str, str, str, str]]:
        """``@a/b/x``: the folders and notes right in ``a/b/`` whose names start with ``x``
        (folders first; ``@x``: the vault's top folders). Hidden folders (``.trash``,
        ``.template``…) are left out unless typed. ``@<vault>/…`` (the first form) is read as
        ``@…``."""
        rest = rest.replace("\xa0", " ")  # a picked folder's spaces (mention_text)
        token = self.ai.vault_token.lower() + "/"
        paths = self.ai.note_paths()
        if rest.lower().startswith(token) and not any(p.lower().startswith(token) for p in paths):
            rest = rest[len(token) :]
        folder, _, start = rest.rpartition("/")
        prefix = f"{folder}/" if folder else ""
        start = start.lower()
        folders: set[str] = set()
        notes: list[str] = []
        for path in paths:
            if not path.lower().startswith(prefix.lower()):
                continue
            inner = path[len(prefix) :]
            if "/" in inner:
                name = inner.split("/", 1)[0]
                if name.lower().startswith(start) and (start or not name.startswith(".")):
                    folders.add(prefix + name)
            elif inner.lower().startswith(start):
                notes.append(path)
        rows = [
            ("folder", f"{path}/", "folder", f"{path.rsplit('/', 1)[-1]}/", "")
            for path in sorted(folders, key=str.lower)
        ]
        # a note's folder is the path already typed: not shown again
        for path in sorted(notes, key=str.lower):
            rows.append(("note", path, "file-text", self._note_row(path)[3], ""))
        return rows[:FOLDER_ROWS]

    def _pick_row(self, kind: str, ident: str, tail: str) -> None:
        if kind == "note":
            self._pick_mention(ident, tail)
        elif kind == "folder":  # complete the path; the list then shows what is in it
            value = self._input.value or ""
            self._input.set_value(value[: len(value) - len(tail)] + mention_text(ident))
            self.focus_input()

    def _picked(self, args: dict[str, object]) -> None:
        """Enter / Tab in the list over the box (``static/chat.js``): its highlighted row."""
        kind, picked = str(args.get("kind", "")), str(args.get("id", ""))
        if kind == "cmd":
            cmd = ai_command(picked)
            if cmd is not None:
                self._pick_command(cmd)
        elif kind in ("note", "folder"):
            m = _MENTION_TAIL.search(self._input.value or "")
            if m and (kind == "folder" or picked in set(self.ai.note_paths())):
                self._pick_row(kind, picked, m.group(0))
        elif kind == "close":
            self._mentions.set_visibility(False)

    def _update_commands(self, query: str) -> None:
        hits = search_commands(query)
        with self._mentions:
            for i, cmd in enumerate(hits):
                row = ui.row().classes(
                    "pp-chat-mention pp-chat-cmd pp-chat-pick items-center no-wrap"
                    + (" pp-chat-pick-active" if i == 0 else "")
                )
                row.props(f'data-kind="cmd" data-id="{cmd.id}"')
                with row:
                    line_icon(cmd.icon)
                    ui.label(cmd.title)
                    ui.label(cmd.subtitle).classes("pp-muted pp-chat-cmd-sub")
                row.on("mousedown.prevent", lambda _e, c=cmd: self._pick_command(c))
        self._mentions.set_visibility(bool(hits))

    def _pick_command(self, cmd: AiCommand) -> None:
        """A command from the ``/`` list: its name in the box; Enter runs it (words after it are
        its instruction, none: the AI suggests options)."""
        self._input.set_value(f"/{command_name(cmd)} ")
        self._mentions.set_visibility(False)
        self.focus_input()

    def _pick_mention(self, path: str, tail: str) -> None:
        name = wikilink_to(path, "", set(self.ai.note_paths()))
        value = self._input.value or ""
        self._input.set_value(value[: len(value) - len(tail)] + mention_text(name) + " ")
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
        if self._asking:
            return  # a question about access is open in the chat
        self._asking = True
        try:
            if not await confirm_access(self.ai, self._card):
                return  # the message stays in the box
            for path in self.ai.paths_to_ask(text):
                if await self._ask_path(path):
                    self.ai.allow_path(path)
        finally:
            self._asking = False
        if self._answering is not None and not text.startswith("/"):
            card, self._answering = self._answering, None  # the answer to the AI's question
            self._input.set_value("")
            words = f"{card.words}\nAnswer: {text}".strip()
            self._run_change(card.command_id, words, card.path, card.selected, offer=False)
            return
        found = parse_command(text)
        if found is not None:
            await self._send_command(*found)
            return
        self._command_card = self._answering = None
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
        show_stop(self._send, True)

    # ---- AI commands from the / list (PLAN §4.28) -------------------------------------------

    def _command_target(self) -> tuple[str, str | None] | None:
        """What a command acts on: the first attached selection (in its note), else the open
        note (whole)."""
        if self._selections:
            picked = self._selections[0]
            path = next(
                (p for p in self.ai.note_paths() if self.ai.link_name(p) == picked.note), None
            )
            return (path, picked.text) if path else None
        path = self._active_path()
        return (path, None) if path else None

    async def _send_command(self, cmd: AiCommand, words: str) -> None:
        target = self._command_target()
        if target is None:
            ui.notify(f"Open a note or attach a selection for /{command_name(cmd)}.")
            return
        path, selected = target
        self._input.set_value("")
        self._mentions.set_visibility(False)
        self._answering = None
        if not words:  # the AI suggests options first
            card = _CommandCard(cmd.id, "", path, selected, busy=True)
            self._show_card(card)
            self._task = background_tasks.create(self._offer(cmd, card))
            show_stop(self._send, True)
        elif cmd.kind == "change":
            self._run_change(cmd.id, words, path, selected)
        else:
            self._send_answer_command(cmd, words, path)

    def _show_card(self, card: _CommandCard | None) -> None:
        self._command_card = card
        self._render_log()

    async def _offer(self, cmd: AiCommand, card: _CommandCard) -> None:
        try:
            note = self.ai.notes.read(card.path) or ""
            body = command_target(note, None)
            text = card.selected or (body.text if body else "")
            options = await suggest_options(self.ai, cmd, path=card.path, note=note, target=text)
            card.options = tuple(options)
        except AccessDeniedError as exc:
            card.message, card.error = str(exc), True
        except asyncio.CancelledError:
            card = None  # type: ignore[assignment]
        finally:
            self._task = None
            show_stop(self._send, False)
            if card is not None:
                card.busy = False
            self._show_card(card)

    def _apply_card(self, card: _CommandCard, instruction: str, groups: tuple[str, ...]) -> None:
        """Apply in a command's options: it runs with the ticked ones as its words."""
        cmd = ai_command(card.command_id)
        if cmd is None or self._task is not None:
            return
        if cmd.kind == "change":
            self._run_change(
                cmd.id, instruction, card.path, card.selected, offer=False, groups=groups
            )
        else:
            self._send_answer_command(cmd, instruction, card.path)

    def _send_answer_command(self, cmd: AiCommand, words: str, path: str) -> None:
        """Summarize, Explain, Outline, Translate: answered in the chat like a message, about
        the attached selection or the whole note."""
        picked, self._selections, self._open = self._selections, [], None
        notes = [] if picked else [path]
        files, self._files = self._files, []
        self._notes = []
        self._command_card = self._answering = None
        self._render_selections()
        self._render_refs()
        out = self.ai.add_message(cmd.instruction(words), picked, notes, files)
        self.ai.save()
        self._task = background_tasks.create(self._answer(out))
        show_stop(self._send, True)

    def _run_change(
        self,
        command_id: str,
        words: str,
        path: str,
        selected: str | None,
        *,
        offer: bool = True,
        how: Again = "again",
        groups: tuple[str, ...] = (),
    ) -> None:
        """Rewrite / Change tone: a diff in the note; when there is none, the card says why."""
        if self._edit_in_note is None or self._task is not None:
            return
        card = _CommandCard(
            command_id, words, path, selected, offer=offer, groups=groups, busy=True
        )
        self._selections, self._open = [], None
        self._render_selections()
        self._show_card(card)
        self._task = background_tasks.create(self._change(card, how))
        show_stop(self._send, True)

    async def _change(self, card: _CommandCard, how: Again) -> None:
        shown: _CommandCard | None = card
        try:
            assert self._edit_in_note is not None
            end = await self._edit_in_note(
                card.path, card.selected, card.command_id, card.words, card.offer, how, card.groups
            )
            if end.kind == "proposal":
                card.message = "The change is shown in the note as a diff."
            elif end.kind == "options":
                card.options = tuple(Option(o) for o in end.options)
                card.options_title = "Which of these do you mean? Pick one or more:"
            else:
                card.message, card.error = end.message, end.kind == "failed"
                if end.kind == "question":
                    self._answering = card
                elif end.kind == "already":
                    card.actions = ("anyway", "change")
                elif end.retry:
                    card.actions = ("again", "change")
                else:
                    card.actions = ("change",)
        except asyncio.CancelledError:
            shown = None
        finally:
            card.busy = False
            self._task = None
            show_stop(self._send, False)
            self._show_card(shown)

    def _card_action(self, card: _CommandCard, action: str) -> None:
        if self._task is not None:
            return
        card.actions = ()
        cmd = ai_command(card.command_id)
        if action == "change" and cmd is not None:
            self._input.set_value(f"/{command_name(cmd)} {card.words}")
            self._render_log()
            self.focus_input()
        elif action == "anyway":
            self._run_change(
                card.command_id,
                card.words,
                card.path,
                card.selected,
                offer=False,
                how="anyway",
                groups=card.groups,
            )
        else:
            self._run_change(
                card.command_id,
                card.words,
                card.path,
                card.selected,
                offer=card.offer,
                groups=card.groups,
            )

    def _render_card(self, card: _CommandCard) -> None:
        cmd = ai_command(card.command_id)
        classes = "pp-msg pp-msg-ai pp-chat-cmdcard" + (" pp-msg-error" if card.error else "")
        with ui.column().classes(classes):
            if cmd is not None:
                ui.label(f"/{command_name(cmd)} {card.words}".strip()).classes(
                    "pp-askpop-msg-cmd pp-chat-cmdcard-cmd"
                )
            if card.busy:
                ui.html(THINKING, sanitize=False).classes("pp-msg-body")
            elif card.options:
                OptionsBox(
                    card.options,
                    lambda i, g, c=card: self._apply_card(c, i, g),
                    title=card.options_title,
                )
            else:
                body = ui.html(render_chat_html(card.message), sanitize=False)
                body.classes("pp-msg-body")
                if card.actions:
                    with ui.row().classes("pp-ai-actions items-center"):
                        for action in card.actions:
                            button = ui.button(
                                ACTION_LABELS[action],
                                on_click=lambda _e, a=action, c=card: self._card_action(c, a),
                                color=None,
                            )
                            main = " pp-ai-action-main" if action != "change" else ""
                            button.props("flat no-caps dense").classes("pp-ai-action" + main)

    async def _answer(self, out: Outgoing) -> None:
        reply = self.ai.start_reply()
        self._answer_started = time.monotonic()  # the info line counts from here (live)
        self._render_log()
        body = self._last_body()
        try:
            snap = await self._snapshot()
            last = 0.0

            def status(text: str) -> None:  # before the first words: say what is going on
                if body is not None and not reply.text:
                    body.set_content(thinking_html(text))

            async for _piece in self.ai.answer(
                reply, out, snap, include_tabs=self._include_tabs, on_status=status
            ):
                now = time.monotonic()
                if body is not None and now - last >= RENDER_EVERY_S:
                    last = now
                    body.set_content(render_chat_html(reply.text))
                    self._scroll_down()
        except asyncio.CancelledError:
            self.ai.stopped(reply)
        except ProviderError as exc:
            self._fail(reply, str(exc), unavailable=isinstance(exc, ProviderUnavailableError))
        except AccessDeniedError as exc:
            self._fail(reply, str(exc))
        except Exception:
            log.exception("chat failed")
            self._fail(reply, "Something went wrong; see the log.")
        finally:
            self.ai.finish_reply(reply, time.monotonic() - self._answer_started)
            self._task = None
            show_stop(self._send, False)
            self._render_log()
            self.ai.save()

    def _last(self, role: str) -> Turn | None:
        return next((t for t in reversed(self.ai.turns) if t.role == role), None)

    def _regenerate(self) -> None:
        """Answer the last message again (the old answer goes)."""
        if self._task is not None:
            return
        out = self.ai.regenerate()
        if out is None:
            return
        self._task = background_tasks.create(self._answer(out))
        show_stop(self._send, True)

    def _edit_last(self) -> None:
        """Take the last message back into the box, with what was attached to it."""
        if self._task is not None:
            return
        turn = self.ai.take_back()
        if turn is None:
            return
        self._selections = [
            Selection(q.text, q.label, q.note, q.kind, q.size if q.kind != "Selected text" else "")
            for q in turn.quotes
        ]
        paths = self.ai.note_paths()
        found = (resolve_wikilink(name, "", paths) for name in turn.notes)
        self._notes = [p for p in found if p is not None]
        self._open = None
        self._render_log()
        self._render_selections()
        self._render_refs()
        self._input.set_value(turn.text)
        self.ai.save()
        self.focus_input()

    async def _ask_path(self, path: Path) -> bool:
        """The message names a folder or file outside the vault: ask in the chat whether the AI
        may read it (remembered for this vault; Settings → AI → Access lists it)."""
        answer: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

        def say(value: bool) -> None:
            if not answer.done():
                answer.set_result(value)

        kind = "folder" if path.is_dir() else "file"
        with self._log:
            card = ui.column().classes("pp-msg pp-chat-ask")
            with card:
                ui.label(f"Allow the AI to read this {kind}?").classes("pp-chat-ask-title")
                tip(ui.label(str(path)).classes("pp-chat-ask-path"), str(path))
                ui.label("Allowed for this vault until you remove it in Settings.").classes(
                    "pp-muted pp-chat-ask-note"
                )
                with ui.row().classes("pp-chat-ask-buttons items-center no-wrap"):
                    ui.button("Not now", on_click=lambda: say(False), color=None).props(
                        "flat dense no-caps"
                    ).classes("pp-mem-change")
                    ui.button("Allow", on_click=lambda: say(True)).props(
                        "dense no-caps unelevated"
                    ).classes("pp-chat-ask-allow")
        self._scroll_down()
        try:
            return await answer
        finally:
            card.delete()

    async def _compact(self) -> None:
        """``/compact``: summarize the earlier messages for the model now."""
        show_stop(self._send, True)
        problem = ""
        try:
            done = await self.ai.compact()
        except asyncio.CancelledError:
            done = False
        except (ProviderError, AccessDeniedError) as exc:
            done, problem = False, f"Could not summarize: {exc}"
        finally:
            self._task = None
            show_stop(self._send, False)
        with self._client:  # a background task has no UI context of its own
            if done:
                self.ai.save()
                self._render_log()
            message = problem or (
                "Earlier messages summarized" if done else "Nothing to summarize yet"
            )
            ui.notify(message, timeout=2500, position="bottom", type="warning" if problem else None)

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
