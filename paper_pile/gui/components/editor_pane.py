"""Center pane: tab bar + editor for the open notes, with autosave and crash recovery.

``core.tabs.TabList`` owns which notes are open and in what order; every tab has its own
:class:`~paper_pile.core.buffer.NoteBuffer` (which decides *what* happens to its text) and its
own editor state in the browser (undo history, cursor), so switching tabs never mixes notes.
This pane decides *when*:

  * a note is saved ~1 s after its last keystroke (the editor reports at 0.3 s, then a 0.7 s
    timer runs), immediately on blur, Ctrl+S, leaving its tab, closing it, and page close;
  * a failed save keeps the text dirty and recoverable and is retried every few seconds.

Every editor event carries the id of the tab it came from, so a late event is routed to its
own note, never the one on screen.
"""

import asyncio
import logging
import os
import time
import webbrowser
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from nicegui import ui

from paper_pile.core import (
    assets,
    commands_builtin,  # noqa: F401  (registers the slash commands)
)
from paper_pile.core.ai.context import EditorSnapshot, build_context
from paper_pile.core.ai.factory import chat_model
from paper_pile.core.ai.provider import ChatMessage, Provider, ProviderError
from paper_pile.core.buffer import NoteBuffer, Outcome, content_hash, find_recoverable
from paper_pile.core.command_actions import TextChange, TextEdit, remove_range, resolve
from paper_pile.core.commands import (
    REGISTRY,
    CommandContext,
    Insert,
    OpenNote,
    OpenPicker,
    StreamInsert,
    UnknownCommandError,
    groups_json,
)
from paper_pile.core.config import Config
from paper_pile.core.events import EventBus
from paper_pile.core.index import Index
from paper_pile.core.links import (
    external_url,
    link_keys,
    new_note_path,
    resolve_md_link,
    resolve_wikilink,
    wikilink_to,
)
from paper_pile.core.parser import find_heading
from paper_pile.core.paste import smart_paste
from paper_pile.core.picker import search_notes
from paper_pile.core.recovery import RecoveryEntry, RecoveryStore
from paper_pile.core.rewrite import Edit, plan_rewrites
from paper_pile.core.snippets import Snippet, link_snippet
from paper_pile.core.tables import apply_op, table_extent
from paper_pile.core.tabs import TabList
from paper_pile.core.templates import render_template
from paper_pile.core.textpos import codepoint_index, utf16_index
from paper_pile.core.vault import Vault, VaultError, is_plain_text
from paper_pile.core.watcher import FsEvent
from paper_pile.gui.components.backlinks import BacklinkItem, BacklinksPane
from paper_pile.gui.components.editor import Editor, Mode
from paper_pile.gui.components.tabs import TabBar
from paper_pile.gui.theme import editor_options

log = logging.getLogger("paper_pile.editor_pane")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


AI_SELECTION_TTL_S = 300.0  # how long a Ctrl+J selection stays usable
STREAM_FLUSH_S = 0.06  # how often streamed text is written into the editor
AUTOSAVE_AFTER_CHANGE_S = 0.7  # on top of the editor's own 0.3 s debounce: ~1 s in total
RETRY_AFTER_FAILURE_S = 5.0


class EditorPane:
    def __init__(
        self,
        vault: Vault,
        bus: EventBus,
        on_state: Callable[[str, bool], None] = lambda text, error: None,
        on_tabs_changed: Callable[[list[str], str | None], None] = lambda paths, active: None,
        mode: Mode = "live",
        on_mode_changed: Callable[[Mode], None] = lambda mode: None,
        native: bool = False,
        on_plain_changed: Callable[[bool], None] = lambda plain: None,
        index: Index | None = None,
        config: Config | None = None,
        get_recents: Callable[[], list[str]] = lambda: [],
        get_provider: Callable[[], Provider | None] = lambda: None,
        user_name: Callable[[], str] = lambda: "",
        on_command_used: Callable[[str], None] = lambda command_id: None,
        add_selection_to_chat: Callable[[str, str], None] = lambda text, path: None,
        add_note_to_chat: Callable[[str], None] = lambda path: None,
    ) -> None:
        self.vault = vault
        self.bus = bus
        self.recovery = RecoveryStore(vault.root)
        self.tabs = TabList()
        self.buffers: dict[int, NoteBuffer] = {}
        self._on_state = on_state
        self._on_tabs_changed = on_tabs_changed
        self.mode: Mode = mode
        self._on_mode_changed = on_mode_changed
        self._native = native  # native window: Python opens links; web mode: the page does
        self._on_plain_changed = on_plain_changed
        self._plain_shown: bool | None = None
        self.theme_name = "light"
        self.index = index
        self._config = config
        self._get_recents = get_recents
        self._get_provider = get_provider
        self._user_name = user_name
        self._ai_selection: dict[str, Any] | None = None  # set by Ctrl+J in the editor
        self._streams = 0
        self._table_lock = asyncio.Lock()  # table edits apply one after the other
        self._on_command_used = on_command_used
        self._add_selection_to_chat = add_selection_to_chat
        self._add_note_to_chat = add_note_to_chat
        self._reindex_handle: asyncio.TimerHandle | None = None
        self._backlinks: BacklinksPane
        self._timer: asyncio.TimerHandle | None = None
        self._failure_toasted = False
        self._rendered: tuple[tuple[int, str], ...] = ()
        self._banner_key: tuple[int, str] | None = None
        self._rendered_active: int | None = None
        self._tabbar: TabBar
        self._editor: Editor
        self._empty: ui.label
        self._banner: ui.element
        self._host: ui.element  # holds dialogs and notifications

    # ---- building ------------------------------------------------------------------------

    def build(self) -> None:
        with ui.column().classes("pp-pane pp-center"):
            self._tabbar = TabBar(
                self.tabs,
                on_activate=self._activate,
                on_close=lambda tab_id: self._spawn(self.close_tab(tab_id)),
                on_move=self._move_tab,
                on_add_to_chat=self._add_note_to_chat,
            )
            self._tabbar.build()
            self._banner = ui.row().classes("pp-banner items-center no-wrap")
            self._banner.set_visibility(False)
            with ui.element("div").classes("pp-editor-area"):
                self._empty = ui.label("Open a note to start writing").classes("pp-muted pp-empty")
                self._editor = Editor(
                    mode=self.mode,
                    link_target="python" if self._native else "window",
                    options=editor_options(self._config),
                    on_link=lambda e: self._on_link(e.args),
                    on_wikilink=lambda e: self._on_wikilink(e.args),
                    on_slash_query=lambda e: self._on_slash_query(e.args),
                    on_slash_run=lambda e: self._spawn(self._on_slash_run(e.args)),
                    on_table_op=lambda e: self._spawn(self._on_table_op(e.args)),
                    on_paste=lambda e: self._on_paste(e.args),
                    on_ai_selection=lambda e: self._on_ai_selection(e.args),
                    on_add_to_chat=lambda e: self._on_add_to_chat(e.args),
                    on_image_saved=lambda e: self._on_image_saved(e.args),
                    on_image_error=lambda e: self._toast(
                        str(e.args.get("message", "")), error=True
                    ),
                    on_image_resize=lambda e: self._spawn(self._on_image_resize(e.args)),
                    image_upload_url="/_pp/upload",
                    on_change=lambda e: self._on_change(e.args),
                    on_blur=lambda e: self._on_flush(e.args),
                    on_save=lambda e: self._on_flush(e.args),
                ).classes("pp-fill")
                self._editor.set_visibility(False)
            self._backlinks = BacklinksPane(
                lambda path, line: self._spawn(self.open_link(path, line=line))
            )
            self._backlinks.build()
        self._host = ui.element("div")
        self.bus.subscribe("tree.open", lambda path: self._spawn(self.open(path)))
        self.bus.subscribe("vault.created", lambda path: self._reindex_soon())
        self.bus.subscribe("vault.renamed", self._renamed_in_app)
        self.bus.subscribe("vault.deleted", lambda path, **_: self._on_deleted(path))
        ui.context.client.on_disconnect(self._on_disconnect)

    def start(self, paths: list[str], active: str | None) -> None:
        """Reopen the tabs of the last session, then offer any crash recovery."""
        self._spawn(self._restore(paths, active))

    def _spawn(self, work: Awaitable[None]) -> None:
        async def guarded() -> None:
            try:
                await work
            except Exception:
                log.exception("editor pane action failed")
                self._toast("Something went wrong; see the log.", error=True)

        asyncio.get_running_loop().create_task(guarded())

    # ---- opening, activating, closing tabs -----------------------------------------------

    async def _restore(self, paths: list[str], active: str | None) -> None:
        if self.index is not None:
            await asyncio.to_thread(self.index.sync)  # backlinks need it before the first tab
        for path in paths:
            if self.vault.exists(path):  # notes deleted since last time are skipped quietly
                await self.open(path, skip_recovery=True, activate=False)
        target = self.tabs.find(active) if active else None
        target = target or (self.tabs.tabs[-1] if self.tabs.tabs else None)
        if target is not None:
            self._activate(target.id)
        else:
            self._notify_tabs()
        entries = find_recoverable(self.vault, self.recovery)
        if entries:
            self._ask_recovery(entries, then_open=None)

    async def open(
        self,
        path: str,
        *,
        recovered: str | None = None,
        skip_recovery: bool = False,
        activate: bool = True,
    ) -> None:
        """Open ``path`` in a tab (or focus its tab). ``recovered`` loads unsaved text instead."""
        existing = self.tabs.find(path)
        if existing is not None:
            if recovered is not None:
                self._apply_recovered(existing.id, recovered)
            if activate:
                self._activate(existing.id)
            return
        if recovered is None and not skip_recovery:
            entry = self.recovery.get(path)
            if entry is not None and self._differs_from_disk(entry):
                self._ask_recovery([entry], then_open=path)
                return
        try:
            buffer = NoteBuffer.open(self.vault, self.recovery, path, recovered=recovered)
        except VaultError as exc:
            self._toast(str(exc), error=True)  # the tabs that are open stay as they are
            return
        tab, _ = self.tabs.open(path)
        self.buffers[tab.id] = buffer
        if activate:
            self._activate(tab.id)
        if buffer.dirty:  # restored text: the editor reports no change for it, so schedule a save
            self._schedule_save(AUTOSAVE_AFTER_CHANGE_S)

    def _differs_from_disk(self, entry: RecoveryEntry) -> bool:
        try:
            return self.vault.read_text(entry.path) != entry.text
        except VaultError:
            return True

    def _apply_recovered(self, tab_id: int, text: str) -> None:
        """Put recovered text into a tab that is already open (it becomes unsaved)."""
        self.buffers[tab_id].set_text(text)
        self._editor.close_doc(tab_id)  # drop its parked state so the new text is what shows
        if tab_id == self.tabs.active:
            self._editor.set_text(text, tab_id, self.buffers[tab_id].path)
        self._schedule_save(AUTOSAVE_AFTER_CHANGE_S)
        self._refresh()

    def _activate(self, tab_id: int) -> None:
        previous = self.tabs.active
        if previous is not None and previous != tab_id and previous in self.buffers:
            self._save_buffer(self.buffers[previous])  # leaving a tab saves it
        self.tabs.activate(tab_id)
        self._empty.set_visibility(False)
        self._editor.set_visibility(True)
        self._editor.show_doc(tab_id, self.buffers[tab_id].text, self.buffers[tab_id].path)
        self._editor.focus()
        self.refresh_links()
        self.refresh_backlinks()
        self._refresh()
        self._notify_tabs()

    def set_theme(self, name: str) -> None:
        """``"light"`` or ``"dark"``: the editor, its code colours and diagrams follow."""
        if name in {"light", "dark"}:
            self.theme_name = name
            self._editor.set_theme("dark" if name == "dark" else "light")

    def set_options(self, options: dict[str, Any]) -> None:
        self._editor.set_options(options)

    def toggle_mode(self) -> None:
        """Live Preview <-> Source. Same text and undo history; only the rendering changes."""
        if self._active_is_plain():
            return  # a .txt note is always plain: there is nothing to toggle
        self.mode = "source" if self.mode == "live" else "live"
        self._editor.set_mode(self.mode)
        self._on_mode_changed(self.mode)

    def close_active(self) -> None:
        if self.tabs.active is not None:
            self._spawn(self.close_tab(self.tabs.active))

    async def close_tab(self, tab_id: int) -> None:
        """Save a tab's note (pulling the freshest text from the browser) and close the tab."""
        buf = self.buffers.get(tab_id)
        if buf is None:
            return
        if tab_id == self.tabs.active:
            self._cancel_timer()
            text = await self._editor.get_text()
            if text is not None:
                buf.set_text(text)
        if not buf.save():
            msg = f"Could not save {buf.path}: {buf.error}. The text is kept for recovery."
            self._toast(msg, error=True)
        elif buf.path.lower().endswith(".md"):
            self._sweep_images(buf.path, buf.text)
        self._drop_tab(tab_id)

    def _sweep_images(self, path: str, text: str) -> None:
        """The note is closed and saved: images it no longer refers to go to the trash."""
        try:
            assets.sweep_orphans(self.vault, path, text)
        except (VaultError, OSError):
            log.exception("could not sweep the images of %s", path)

    def _drop_tab(self, tab_id: int) -> None:
        """Remove a tab (its buffer is already saved or deliberately discarded)."""
        was_active = tab_id == self.tabs.active
        self.buffers.pop(tab_id, None)
        next_active = self.tabs.close(tab_id)
        if next_active is not None and was_active:
            self._activate(next_active)  # switches the editor away from the closed tab first
        elif next_active is None:
            self._editor.set_visibility(False)
            self._empty.set_visibility(True)
        self._editor.close_doc(tab_id)  # only now: the closed tab's state must not be parked again
        self._refresh()
        self._notify_tabs()

    def cycle(self, step: int) -> None:
        target = self.tabs.cycle(step)
        if target is not None and target != self.tabs.active:
            self._activate(target)

    def _move_tab(self, src: int, dst: int, after: bool) -> None:
        if self.tabs.move(src, dst, after=after):
            self._refresh()
            self._notify_tabs()

    # ---- events from the editor ----------------------------------------------------------

    def _on_change(self, args: dict[str, Any]) -> None:
        tab_id = int(args.get("docId", -1))
        buf = self.buffers.get(tab_id)
        if buf is None:
            return  # a late event from a tab that has since been closed
        buf.set_text(str(args["text"]))
        if tab_id == self.tabs.active:
            self._schedule_save(AUTOSAVE_AFTER_CHANGE_S)
        else:  # the editor flushed a tab we just left: save it right away
            self._save_buffer(buf)
        self._refresh()

    def _on_flush(self, args: dict[str, Any]) -> None:
        """Blur / Ctrl+S: take the text and save right now."""
        buf = self.buffers.get(int(args.get("docId", -1)))
        if buf is None:
            return
        buf.set_text(str(args["text"]))
        self._save_buffer(buf)
        self._refresh()

    def _active_is_plain(self) -> bool:
        tab = self.tabs.active_tab
        return tab is not None and is_plain_text(tab.path)

    def _on_slash_query(self, args: dict[str, Any]) -> None:
        """The text after a typed ``/`` changed: answer with the commands that match it."""
        path = self._active_path()
        if path is None or args.get("docId") != self.tabs.active:
            return
        buffer = self.buffers[self.tabs.active]
        sel = self._ai_selection
        selected = (
            sel is not None
            and sel["docId"] == args.get("docId")
            and sel["to"] == args.get("from")
            and time.monotonic() - sel["at"] < AI_SELECTION_TTL_S
            and sel["to"] > sel["from"]
        )
        ctx = CommandContext(
            path,
            buffer.text,
            0,
            selection=(int(sel["from"]), int(sel["to"])) if selected and sel else None,
            vault=self.vault,
            config=self._config,
        )
        groups = REGISTRY.search(str(args.get("q", "")), ctx, self._get_recents())
        self._editor.set_slash_results(int(args.get("seq", 0)), groups_json(groups))

    async def _on_slash_run(self, args: dict[str, Any]) -> None:
        """A command was picked in the slash menu: run it and apply the resulting edit."""
        tab_id = self.tabs.active
        path = self._active_path()
        if tab_id is None or path is None or args.get("docId") != tab_id:
            return
        text = await self._editor.get_text()  # the browser may hold keystrokes we have not seen
        if text is None:
            return
        start = codepoint_index(text, int(args["from"]))
        end = codepoint_index(text, int(args["to"]))
        if text[start : start + 1] != "/" or end < start:
            return  # the text moved on since the pick
        selection = self._selection_for(text, start)
        ctx = CommandContext(
            path, text, start, selection=selection, vault=self.vault, config=self._config, end=end
        )
        try:
            action = REGISTRY.run(str(args["id"]), ctx)
        except UnknownCommandError:
            log.warning("slash menu asked for an unknown command %r", args.get("id"))
            return
        edit = resolve(action, text, start, end) or remove_range(start, end)
        if not await self._apply_edit(tab_id, text, edit):
            return  # a keystroke raced the round trip; the typed /query is left as it was
        self._on_command_used(str(args["id"]))
        if isinstance(action, Insert) and action.focus_cell is not None:
            table_start = edit.changes[0].start + (1 if action.text.startswith("\n") else 0)
            row, col = action.focus_cell
            self._editor.focus_table_cell(row, col, utf16_index(text, table_start))
        if isinstance(action, OpenNote):
            await self.open_link(action.path)
        elif isinstance(action, OpenPicker) and action.kind == "image":
            self._editor.pick_image()
        elif isinstance(action, OpenPicker):
            self._open_picker(action, path)
        elif isinstance(action, StreamInsert):
            await self._run_stream(action, tab_id, text, start, end, selection)

    # ---- the note picker (link to note, embed note, templates) ---------------------------

    def _open_picker(self, action: OpenPicker, source: str) -> None:
        """Let the user pick a note; what is inserted depends on the command that asked."""
        notes = list(self.vault.walk_notes())
        title = "Insert template" if action.command_id == "template" else "Choose a note"
        if action.command_id == "template":
            folder = (
                str(self._config.get("vault.templates_folder", "")).strip("/")
                if self._config
                else ""
            )
            notes = [n for n in notes if n.startswith(folder + "/")]
        state = {"query": "", "selected": 0}
        shown: list[str] = []
        with self._host, ui.dialog() as dialog, ui.card().classes("pp-dialog pp-picker"):
            ui.label(title).classes("pp-dialog-title")
            field = ui.input(placeholder="Search notes…").props("outlined dense autofocus")
            listing = ui.column().classes("pp-picker-list")

            def render() -> None:
                shown[:] = search_notes(state["query"], notes)
                state["selected"] = min(state["selected"], max(0, len(shown) - 1))
                listing.clear()
                with listing:
                    if not shown:
                        ui.label("No notes found").classes("pp-muted")
                    for i, path in enumerate(shown):
                        folder_part, _, name = path.rpartition("/")
                        row = ui.row().classes("pp-picker-row items-baseline no-wrap")
                        if i == state["selected"]:
                            row.classes("pp-picker-sel")
                        with row:
                            ui.label(name.rsplit(".", 1)[0])
                            if folder_part:
                                ui.label(folder_part).classes("pp-muted")
                        row.on("click", lambda _e, p=path: choose(p))

            def move(delta: int) -> None:
                if shown:
                    state["selected"] = (state["selected"] + delta) % len(shown)
                    render()

            def choose(path: str | None = None) -> None:
                picked = path if path is not None else (shown[state["selected"]] if shown else None)
                if picked is None:
                    return
                dialog.close()
                self._insert_picked(action, source, picked)

            def filter_changed(e: Any) -> None:
                state["query"], state["selected"] = str(e.value or ""), 0
                render()

            field.on_value_change(filter_changed)
            field.on("keydown.down.prevent", lambda _e: move(1))
            field.on("keydown.up.prevent", lambda _e: move(-1))
            field.on("keydown.enter.prevent", lambda _e: choose())
            dialog.on("hide", lambda _e: self._editor.focus())
            render()
        dialog.open()

    def _insert_picked(self, action: OpenPicker, source: str, picked: str) -> None:
        notes = set(self.vault.walk_notes())
        if action.command_id == "template":
            try:
                body = self.vault.read_text(picked)
            except VaultError as exc:
                self._toast(str(exc), error=True)
                return
            stem = source.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            text = render_template(body, title=stem, now=datetime.now())
        else:
            link = f"[[{wikilink_to(picked, source, notes)}]]"
            text = "!" + link if action.command_id == "embed" else link
        self._editor.insert_at_cursor(text)

    def _on_paste(self, args: dict[str, Any]) -> None:
        """Text or HTML was pasted (Ctrl+Shift+V never gets here: that is a raw paste). With Smart
        Paste on, math, code, tables and lists are turned into clean markdown."""
        if self.tabs.active is None or args.get("kind") not in {"html", "text"}:
            return
        html, text = str(args.get("html") or ""), str(args.get("text") or "")
        self._dump_paste(html, text)
        enabled = bool(self._config.get("paste.smart_paste", True)) if self._config else True
        converted = smart_paste(html, text) if enabled else text
        if converted:
            self._editor.insert_at_cursor(converted)

    def _dump_paste(self, html: str, text: str) -> None:
        """With ``PAPER_PILE_DUMP_PASTE=1`` keep what the clipboard held (for test fixtures)."""
        if not os.environ.get("PAPER_PILE_DUMP_PASTE"):
            return
        folder = self.vault.root / ".paper-pile" / "paste-dumps"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            (folder / f"{stamp}.html").write_text(html, encoding="utf-8")
            (folder / f"{stamp}.txt").write_text(text, encoding="utf-8")
            log.info("clipboard saved to %s", folder / stamp)
        except OSError:
            log.exception("could not save the clipboard dump")

    async def ai_snapshot(self) -> EditorSnapshot:
        """The open note, the selected text and the open tabs, as the AI features need them."""
        path = self._active_path()
        if path is None:
            return EditorSnapshot()
        fresh = await self._editor.get_text()
        text = fresh if fresh is not None else self.buffers[self.tabs.active or 0].text
        picked = await self._editor.get_selection()
        tabs = [(b.path, b.text) for b in self.buffers.values()]
        return EditorSnapshot(path, text, picked[0] if picked else "", tabs)

    def insert_text(self, text: str) -> None:
        """Put ``text`` at the caret of the note on screen (replacing a selection)."""
        if self.tabs.active is not None:
            self._editor.insert_at_cursor(text)

    def _on_image_saved(self, args: dict[str, Any]) -> None:
        """An image was pasted, dropped or picked and stored: insert its markdown at the caret."""
        path = self._active_path()
        if path is None or args.get("docId") != self.tabs.active:
            self._toast("The image was saved, but the note changed before it could be inserted.")
            return
        ref = str(args.get("ref", ""))
        try:
            self.vault.asset_path(path, ref)  # it must be an image of this note that really exists
        except VaultError as exc:
            self._toast(str(exc), error=True)
            return
        width = args.get("width")
        self._editor.insert_at_cursor(
            assets.image_markdown(ref, width if isinstance(width, int) else None)
        )

    async def _on_image_resize(self, args: dict[str, Any]) -> None:
        """The user dragged an image's corner: rewrite only the ``|width`` in its markdown."""
        tab_id = self.tabs.active
        if tab_id is None or args.get("docId") != tab_id:
            return
        text = await self._editor.get_text()
        if text is None:
            return
        start = codepoint_index(text, int(args["from"]))
        change = assets.set_width_edit(text, start, int(args["width"]))
        if change is None:
            return
        edit = TextEdit((TextChange(change.start, change.end, change.insert),), change.start)
        await self._apply_edit(tab_id, text, edit, move_caret=False)

    async def _on_table_op(self, args: dict[str, Any]) -> None:
        """The user edited a table (typed in a cell, added a row, ...): Python decides what the
        markdown becomes (``core/tables.py``) and the editor applies it as one undo step."""
        async with self._table_lock:
            tab_id = self.tabs.active
            op = args.get("op")
            if tab_id is None or args.get("docId") != tab_id or not isinstance(op, dict):
                return
            text = await self._editor.get_text()
            if text is None:
                return
            start = codepoint_index(text, int(args["from"]))
            end = table_extent(text, start)  # measured here: earlier edits may have resized it
            if end is None:
                return
            result = apply_op(text[start:end], op)
            if result is None or result.text == text[start:end]:
                return
            edit = TextEdit((TextChange(start, end, result.text),), start)
            await self._apply_edit(tab_id, text, edit, move_caret=False)

    # ---- AI commands (slash menu, selection) ---------------------------------------------

    def _on_add_to_chat(self, args: dict[str, Any]) -> None:
        text = str(args.get("text", ""))
        if text.strip():
            self._add_selection_to_chat(text, self._active_path() or "")

    def open_paths(self) -> list[str]:
        """Paths of every open tab, in tab order."""
        return [tab.path for tab in self.tabs.tabs]

    def _on_ai_selection(self, args: dict[str, Any]) -> None:
        """Ctrl+J: the editor reports what is selected before it opens the menu."""
        self._ai_selection = {
            "docId": args.get("docId"),
            "from": int(args.get("from", 0)),
            "to": int(args.get("to", 0)),
            "text": str(args.get("text", "")),
            "at": time.monotonic(),
        }

    def _selection_for(self, text: str, start: int) -> tuple[int, int] | None:
        """The text selected before Ctrl+J, if the ``/`` just typed sits right after it."""
        sel = self._ai_selection
        if sel is None or sel["docId"] != self.tabs.active or not sel["text"]:
            return None
        if time.monotonic() - sel["at"] > AI_SELECTION_TTL_S:
            return None
        a, b = codepoint_index(text, sel["from"]), codepoint_index(text, sel["to"])
        return (a, b) if b == start and text[a:b] == sel["text"] else None

    async def _ask_dialog(self) -> str | None:
        """Ask what to ask the AI; ``None`` if cancelled."""
        with self._host, ui.dialog() as dialog, ui.card().classes("pp-dialog pp-ask"):
            ui.label("Ask the AI").classes("pp-dialog-title")
            ui.label("It sees this note. The answer is written at the caret.").classes("pp-muted")
            box = ui.textarea(placeholder="What should it write?").props(
                "outlined autofocus autogrow"
            )
            box.classes("w-full")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
                ask = ui.button("Ask", on_click=lambda: dialog.submit((box.value or "").strip()))
                ask.props("no-caps")
            box.on("keydown.ctrl.enter", lambda _e: dialog.submit((box.value or "").strip()))
        dialog.open()
        answer = await dialog
        return str(answer) if answer else None

    async def _run_stream(
        self,
        spec: StreamInsert,
        tab_id: int,
        text: str,
        anchor: int,
        end: int,
        selection: tuple[int, int] | None,
    ) -> None:
        """Run an AI command: ask the model and write its answer into the note as it arrives."""
        provider = self._get_provider()
        path = self._active_path()
        if provider is None or path is None:
            self._toast("AI is not available.", error=True)
            return
        question = ""
        if spec.ask:
            asked = await self._ask_dialog()
            if not asked:
                return
            question = asked
        # the "/query" was removed already: the note is now `text` without text[anchor:end]
        selected = text[selection[0] : selection[1]] if selection else ""
        body_text = text[:anchor] + text[end:]
        source = spec.source if spec.source != "auto" else ("selection" if selected else "note")
        part = {"selection": selected, "before": body_text[max(0, anchor - 4000) : anchor]}.get(
            source, ""
        )
        context = build_context(
            self.vault,
            current_path=path,
            current_text=body_text,
            selection=selected if source == "selection" else "",
            index=self.index,
            budget=int(self._config.get("ai.context_budget", 6000)) if self._config else 6000,
        )
        task_text = question or spec.instruction
        user = task_text + (f"\n\nText:\n{part}" if part else "")
        rules = (
            ""
            if spec.ask
            else "\n\nReply with only the text to put into the note: no introduction, no "
            "comments about what you did, and no code block around the answer."
        )
        messages = [
            ChatMessage("system", context.system_prompt(self._user_name()) + rules),
            ChatMessage("user", user),
        ]
        self._streams += 1
        stream_id = self._streams
        task = asyncio.current_task()
        finished = False

        def stop() -> None:
            if not finished and task is not None:
                task.cancel()

        with self._host:
            note = ui.notification(
                "AI is writing…", spinner=True, timeout=None, close_button="Stop", on_dismiss=stop
            )
        collected = ""
        pending = ""
        last = time.monotonic()
        live = not spec.replace_selection
        try:
            if live:
                await self._editor.stream_begin(stream_id, utf16_index(body_text, anchor))
                if spec.lead and not await self._editor.stream_append(stream_id, spec.lead):
                    return
            async for piece in provider.chat(messages, model=chat_model(provider, self._config)):
                collected += piece
                pending += piece
                if live and time.monotonic() - last >= STREAM_FLUSH_S:
                    if not await self._editor.stream_append(stream_id, pending):
                        return  # another note was opened: the answer stops here
                    pending, last = "", time.monotonic()
            if live and pending:
                await self._editor.stream_append(stream_id, pending)
            elif spec.replace_selection and selection:
                await self._replace_selection(tab_id, selected, collected.strip("\n"), selection[0])
        except ProviderError as exc:
            self._toast(str(exc), error=True)
        finally:
            finished = True
            note.dismiss()
            if live:
                self._editor.stream_end(stream_id)

    async def _replace_selection(self, tab_id: int, original: str, result: str, start: int) -> None:
        """Replace the selected text by the AI's version, as one undo step."""
        if not result.strip():
            return
        text = await self._editor.get_text()
        if text is None or text[start : start + len(original)] != original:
            self._toast(
                "The text changed while the AI was writing; nothing was replaced.", error=True
            )
            return
        edit = TextEdit((TextChange(start, start + len(original), result),), start + len(result))
        await self._apply_edit(tab_id, text, edit)

    async def _apply_edit(
        self, tab_id: int, before: str, edit: TextEdit, *, move_caret: bool = True
    ) -> bool:
        """Apply a command's edit to the note on screen as one undo step (buffer kept in step)."""
        after = before
        for change in sorted(edit.changes, key=lambda c: c.start, reverse=True):
            after = after[: change.start] + change.insert + after[change.end :]
        changes = [
            {
                "from": utf16_index(before, c.start),
                "to": utf16_index(before, c.end),
                "insert": c.insert,
            }
            for c in edit.changes
        ]
        cursor = utf16_index(after, edit.cursor) if move_caret else None
        if not await self._editor.apply_changes(tab_id, changes, before, cursor):
            return False
        self.buffers[tab_id].set_text(after)
        self._schedule_save(AUTOSAVE_AFTER_CHANGE_S)
        return True

    def _on_link(self, args: dict[str, Any]) -> None:
        """Ctrl/Cmd+click on a link. Web links open in the browser (here, in the native window;
        in web mode the page already opened them). A relative link to a note opens that note."""
        href = str(args.get("href", ""))
        url = external_url(href)
        if url is not None:
            if self._native:
                try:
                    webbrowser.open(url)
                except Exception:
                    log.exception("could not open %s", url)
                    self._toast("Could not open the link.", error=True)
            return
        source = self._active_path()
        target = resolve_md_link(href, source, set(self.vault.walk_notes())) if source else None
        if target is None:
            self._toast(f"No note found for {href}", error=True)
            return
        fragment = href.partition("#")[2]
        self._spawn(self.open_link(target, fragment))

    def _on_wikilink(self, args: dict[str, Any]) -> None:
        """Ctrl/Cmd+click on ``[[note#heading]]``: open the note (at the heading), or create it."""
        source = self._active_path()
        if source is None:
            return
        note, heading = str(args.get("note", "")), str(args.get("heading", ""))
        target = resolve_wikilink(note, source, list(self.vault.walk_notes()))
        if target is None:
            target = self._create_missing(note, source)
            if target is None:
                return
        self._spawn(self.open_link(target, heading))

    def _create_missing(self, note: str, source: str) -> str | None:
        """Create the note a wikilink points at (next to the source note); returns its path."""
        path = new_note_path(note, source)
        if path is None:
            self._toast(f"“{note}” is not a valid note name.", error=True)
            return None
        try:
            if not self.vault.exists(path):
                self.vault.create_note(path)
                self.bus.publish("vault.created", path=path)
        except VaultError as exc:
            self._toast(str(exc), error=True)
            return None
        self._toast(f"Created {path}")
        return path

    async def open_link(self, path: str, heading: str = "", *, line: int = 0) -> None:
        """Open ``path`` in a tab and jump to ``line``, or to the heading named ``heading``."""
        await self.open(path)
        tab = self.tabs.find(path)
        if tab is None or tab.id != self.tabs.active:
            return
        if line:
            self._editor.goto_line(line)
            return
        if not heading:
            return
        found = find_heading(self.buffers[tab.id].text, heading)
        if found is not None:
            self._editor.goto_line(found.line)
        else:
            self._toast(f"No heading “{heading}” in {path}")

    def _active_path(self) -> str | None:
        active = self.tabs.active
        return self.buffers[active].path if active in self.buffers else None

    # ---- index and backlinks -------------------------------------------------------------

    def _reindex_soon(self) -> None:
        """Bring the index in line with the vault (debounced, off the UI thread)."""
        if self.index is None:
            return
        if self._reindex_handle is not None:
            self._reindex_handle.cancel()
        self._reindex_handle = asyncio.get_running_loop().call_later(
            0.3, lambda: self._spawn(self._reindex())
        )

    async def _reindex(self) -> None:
        self._reindex_handle = None
        if self.index is None:
            return
        await asyncio.to_thread(self.index.sync)
        self.refresh_backlinks()

    def refresh_backlinks(self) -> None:
        """List the notes linking to the active note."""
        path = self._active_path()
        if self.index is None or path is None:
            self._backlinks.set_items([])
            return
        items = []
        for link in self.index.backlinks(path)[:100]:
            try:
                text = self.vault.read_text(link.src)
                snippet = link_snippet(text, link.line, link.kind, link.raw)
            except VaultError:
                snippet = Snippet("", "", "")
            items.append(BacklinkItem(link.src, link.title, link.line, snippet))
        self._backlinks.set_items(items)

    def refresh_links(self) -> None:
        """Tell the editor which notes exist, so links to missing ones are styled."""
        self._editor.set_known_notes(link_keys(self.vault.walk_notes()))

    def _on_disconnect(self) -> None:
        self._cancel_timer()
        if self._reindex_handle is not None:
            self._reindex_handle.cancel()
        if self.index is not None:
            self.index.close()
        for buf in self.buffers.values():
            buf.save()

    # ---- saving --------------------------------------------------------------------------

    def _schedule_save(self, delay: float) -> None:
        self._cancel_timer()
        self._timer = asyncio.get_running_loop().call_later(delay, self._save_all)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _save_all(self) -> None:
        """Autosave tick: write every unsaved note; retry later if any write failed."""
        self._cancel_timer()
        failed = False
        for buf in self.buffers.values():
            if buf.conflict is None and buf.dirty and not self._save_buffer(buf, refresh=False):
                failed = True
        if failed:
            self._schedule_save(RETRY_AFTER_FAILURE_S)
        else:
            self._failure_toasted = False
        self._refresh()

    def _save_buffer(self, buf: NoteBuffer, *, refresh: bool = True) -> bool:
        if buf.conflict is not None:  # waiting for the user's decision: never write over theirs
            return False
        ok = buf.save()
        if ok and self.index is not None:
            self.index.update_note(buf.path)
            if buf.path != self._active_path():
                self.refresh_backlinks()  # a background note changed what links here
        if not ok and not self._failure_toasted:
            self._failure_toasted = True
            self._toast(f"Could not save {buf.path}: {buf.error}", error=True)
        if not ok:
            self._schedule_save(RETRY_AFTER_FAILURE_S)
        if refresh:
            self._refresh()
        return ok

    # ---- keeping the tab bar and status bar in step --------------------------------------

    def _unsaved(self) -> dict[int, bool]:
        return {
            i: b.dirty or bool(b.error) or b.conflict is not None for i, b in self.buffers.items()
        }

    def _refresh(self) -> None:
        unsaved = self._unsaved()
        if self._structure_changed():
            self._tabbar.render(unsaved)
        else:
            self._tabbar.set_unsaved(unsaved)
        self._show_state()
        self._update_banner()
        plain = self._active_is_plain()
        if plain != self._plain_shown:
            self._plain_shown = plain
            self._on_plain_changed(plain)

    def _structure_changed(self) -> bool:
        """Re-render the bar only when tabs, titles or the active tab changed (not on typing)."""
        shape = tuple((t.id, t.path) for t in self.tabs.tabs)
        if shape == self._rendered and self.tabs.active == self._rendered_active:
            return False
        self._rendered, self._rendered_active = shape, self.tabs.active
        return True

    def _show_state(self) -> None:
        tab = self.tabs.active_tab
        buf = self.buffers.get(tab.id) if tab else None
        if buf is None:
            self._on_state("Ready", False)
        elif buf.conflict is not None:
            self._on_state("Changed on disk", True)
        elif buf.error:
            self._on_state("Save failed", True)
        elif buf.dirty:
            self._on_state("Editing…", False)
        else:
            self._on_state("Saved", False)

    def _notify_tabs(self) -> None:
        active = self.tabs.active_tab
        self._on_tabs_changed(self.tabs.paths, active.path if active else None)

    # ---- changes made outside the app ------------------------------------------------------

    def on_external(self, events: list[FsEvent]) -> None:
        """The watcher saw files change on disk (a terminal, another editor, a sync tool)."""
        self.refresh_links()  # notes may have appeared or vanished
        self._reindex_soon()
        self._spawn(self._handle_external(events))

    async def _handle_external(self, events: list[FsEvent]) -> None:
        for e in events:
            if e.kind == "moved" and e.old_path is not None:
                self._on_renamed(
                    e.old_path, e.path
                )  # the tab follows the note (no-op if we moved it)
        files = {e.path for e in events if not e.is_dir}
        ids = {t.id for t in self.tabs.tabs if t.path in files}
        for e in events:
            if e.is_dir:  # a folder was moved/deleted: look at the notes inside it
                ids |= {t.id for t in self.tabs.under(e.path)}
        for tab_id in sorted(ids):
            await self._sync_tab(tab_id)

    async def _sync_tab(self, tab_id: int) -> None:
        """Compare one open note with the disk and react (the rules live in NoteBuffer)."""
        buf = self.buffers.get(tab_id)
        if buf is None:
            return
        if tab_id == self.tabs.active:
            # the browser may hold keystrokes we have not been told about yet
            text = await self._editor.get_text()
            buf = self.buffers.get(tab_id)
            if buf is None:
                return
            if text is not None:
                buf.set_text(text)
        outcome = buf.sync_with_disk()
        name = buf.path.rsplit("/", 1)[-1]
        if outcome is Outcome.RELOADED:
            self._show_text(tab_id, keep_caret=True)
        elif outcome is Outcome.GONE:
            self._toast(f"“{name}” was deleted outside the app; its tab was closed.")
            self._drop_tab(tab_id)
            return
        elif outcome in (Outcome.CONFLICT, Outcome.CONFLICT_GONE) and tab_id != self.tabs.active:
            self._toast(f"“{name}” changed outside the app and has unsaved edits here.", error=True)
        self._refresh()

    def _show_text(self, tab_id: int, *, keep_caret: bool = False) -> None:
        """Put a buffer's text on screen after it was replaced from outside the editor."""
        buf = self.buffers[tab_id]
        if tab_id == self.tabs.active:
            self._editor.set_text(buf.text, tab_id, buf.path, keep_caret=keep_caret)
        else:
            self._editor.close_doc(tab_id)  # drop the parked state; the next switch shows buf.text

    def _update_banner(self) -> None:
        """The conflict banner above the editor, for the active tab only."""
        tab = self.tabs.active_tab
        buf = self.buffers.get(tab.id) if tab else None
        conflict = buf.conflict if buf else None
        if tab is None or buf is None or conflict is None:
            if self._banner_key is not None:
                self._banner_key = None
                self._banner.set_visibility(False)
            return
        key = (tab.id, "gone" if conflict.text is None else content_hash(conflict.text))
        if key == self._banner_key:
            return
        self._banner_key = key
        name = buf.path.rsplit("/", 1)[-1]
        self._banner.clear()
        gone = conflict.text is None
        message = (
            f"“{name}” was deleted or moved outside the app."
            if gone
            else f"“{name}” changed outside the app, and you have unsaved edits."
        )
        choices = (
            [("Keep editing", self._keep_mine), ("Close and discard", self._close_discard)]
            if gone
            else [("Keep mine", self._keep_mine), ("Load theirs", self._load_theirs)]
        )
        with self._banner:
            ui.label(message).classes("pp-banner-text")
            for label, handler in choices:
                button = ui.button(label, on_click=lambda _e=None, h=handler, i=tab.id: h(i))
                button.props("flat dense no-caps")
        self._banner.set_visibility(True)

    # The losing side of every choice is stashed in .trash first: resolving a conflict never
    # destroys text.

    def _keep_mine(self, tab_id: int) -> None:
        buf = self.buffers.get(tab_id)
        if buf is None or buf.conflict is None:
            return
        if buf.conflict.text is not None:
            where = self.vault.stash_text(buf.path, buf.conflict.text, "changed on disk")
            self._toast(f"Kept your version. The other one is in {where}.")
        buf.keep_mine()
        self._schedule_save(AUTOSAVE_AFTER_CHANGE_S)
        self._refresh()

    def _load_theirs(self, tab_id: int) -> None:
        buf = self.buffers.get(tab_id)
        if buf is None or buf.conflict is None or buf.conflict.text is None:
            return
        where = self.vault.stash_text(buf.path, buf.text, "my unsaved edits")
        self._toast(f"Loaded the version from disk. Your edits are in {where}.")
        buf.load_theirs()
        self._show_text(tab_id)
        self._refresh()

    def _close_discard(self, tab_id: int) -> None:
        buf = self.buffers.get(tab_id)
        if buf is None:
            return
        where = self.vault.stash_text(buf.path, buf.text, "my unsaved edits")
        self._toast(f"Closed. Your edits are in {where}.")
        buf.discard()
        self._drop_tab(tab_id)

    # ---- the tree renamed / deleted notes ------------------------------------------------

    def _on_renamed(self, old: str, new: str) -> None:
        changed = self.tabs.rename_prefix(old, new)
        for tab in changed:
            self.buffers[tab.id].rename(tab.path)
            if tab.id == self.tabs.active:
                self._editor.set_path(tab.path)  # relative image URLs depend on the note's folder
        self.refresh_links()
        self._reindex_soon()
        if changed:
            self._refresh()
            self._notify_tabs()

    def _renamed_in_app(self, old: str, new: str) -> None:
        """The tree renamed or moved something: tabs follow it, and links are repaired.
        (Renames seen by the watcher only move tabs: outside changes are left alone.)"""
        self._on_renamed(old, new)
        self._spawn(self._rewrite_links(old, new))

    async def _rewrite_links(self, old: str, new: str) -> None:
        """Keep every link pointing at the note it pointed at (rules: ``core/rewrite.py``)."""
        if self.index is None:
            return
        moves = self._moves(old, new)
        if not moves:
            return
        active = self.tabs.active
        if active in self.buffers:
            text = await self._editor.get_text()  # the browser may hold unreported keystrokes
            if text is not None:
                self.buffers[active].set_text(text)
        await asyncio.to_thread(self.index.sync)
        keys = set(link_keys(moves)) | set(link_keys(moves.values()))
        candidates = self.index.link_sources(keys) | set(moves.values())
        open_tabs = {t.path: t.id for t in self.tabs.tabs if t.id in self.buffers}
        texts: dict[str, str] = {}
        for path in sorted(candidates):
            try:
                if path in open_tabs:
                    texts[path] = self.buffers[open_tabs[path]].text.replace("\r\n", "\n")
                else:
                    texts[path] = self.vault.read_text(path)
            except VaultError:
                continue
        plan = plan_rewrites(moves, set(self.index.paths()), texts)
        links = notes = 0
        skipped = plan.skipped
        for path, edits in plan.edits.items():
            if path in open_tabs:
                done = await self._rewrite_open(
                    open_tabs[path], texts[path], edits, plan.texts[path]
                )
            else:
                done = self._rewrite_closed(path, texts[path], plan.texts[path])
            if done:
                links += len(edits)
                notes += 1
            else:
                skipped += len(edits)
        await asyncio.to_thread(self.index.sync)
        self.refresh_links()
        self.refresh_backlinks()
        self._refresh()
        if links:
            self._toast(f"Updated {_count(links, 'link')} in {_count(notes, 'note')}")
        if skipped:
            self._toast(f"{_count(skipped, 'link')} could not be updated automatically", error=True)

    def _moves(self, old: str, new: str) -> dict[str, str]:
        """Old path -> new path of every note a rename/move of ``old`` to ``new`` carried along."""
        if not self.vault.exists(new):
            return {}
        if self.vault.resolve(new).is_file():
            return {old: new}
        prefix = new + "/"
        return {old + p[len(new) :]: p for p in self.vault.walk_notes() if p.startswith(prefix)}

    async def _rewrite_open(self, tab_id: int, before: str, edits: list[Edit], after: str) -> bool:
        """Apply a link rewrite to a note that is open in a tab (undo history kept)."""
        changes = [
            {
                "from": utf16_index(before, e.start),
                "to": utf16_index(before, e.end),
                "insert": e.insert,
            }
            for e in edits
        ]
        if not await self._editor.apply_changes(tab_id, changes, before):
            return False
        self.buffers[tab_id].set_text(after)
        self._schedule_save(AUTOSAVE_AFTER_CHANGE_S)
        return True

    def _rewrite_closed(self, path: str, before: str, after: str) -> bool:
        """Write a link rewrite to a note nobody is editing; only if it is still as planned."""
        try:
            if self.vault.read_text(path) != before:
                return False
            self.vault.write_text(path, after)
        except (VaultError, OSError):
            log.exception("could not rewrite links in %s", path)
            return False
        return True

    def _on_deleted(self, path: str) -> None:
        for tab in self.tabs.under(path):
            buf = self.buffers.get(tab.id)
            if buf is not None:
                buf.discard()  # its note is in .trash now; saving would bring it back
            self._drop_tab(tab.id)
        self.refresh_links()
        self._reindex_soon()

    # ---- crash recovery ------------------------------------------------------------------

    def _ask_recovery(self, entries: list[RecoveryEntry], *, then_open: str | None) -> None:
        """One dialog listing unsaved text that survived a crash or a failed save."""
        with self._host, ui.dialog() as dialog, ui.card().classes("pp-dialog pp-recovery"):
            ui.label("Unsaved changes were recovered").classes("pp-dialog-title")
            ui.label("These notes had text that never reached the disk.").classes("pp-muted")
            for entry in entries:
                with ui.row().classes("items-center w-full no-wrap pp-recovery-row"):
                    when = time.strftime("%H:%M:%S", time.localtime(entry.saved_at))
                    ui.label(entry.path).classes("pp-recovery-path")
                    ui.label(when).classes("pp-muted")
                    ui.space()
                    ui.button(
                        "Restore", on_click=lambda e=entry: self._restore_entry(dialog, e)
                    ).props("dense no-caps")
                    ui.button(
                        "Discard", on_click=lambda e=entry: self._discard(dialog, e, then_open)
                    ).props("flat dense no-caps")
            later = ui.button("Later", on_click=lambda: self._later(dialog, then_open))
            later.props("flat no-caps")
        dialog.open()

    def _restore_entry(self, dialog: ui.dialog, entry: RecoveryEntry) -> None:
        dialog.close()
        self._spawn(self.open(entry.path, recovered=entry.text))

    def _discard(self, dialog: ui.dialog, entry: RecoveryEntry, then_open: str | None) -> None:
        self.recovery.clear(entry.path)
        dialog.close()
        if then_open == entry.path:
            self._spawn(self.open(entry.path, skip_recovery=True))

    def _later(self, dialog: ui.dialog, then_open: str | None) -> None:
        dialog.close()
        if then_open is not None:
            self._spawn(self.open(then_open, skip_recovery=True))

    # ---- toasts --------------------------------------------------------------------------

    def _toast(self, message: str, *, error: bool = False) -> None:
        with self._host:
            ui.notify(message, type="negative" if error else None)
