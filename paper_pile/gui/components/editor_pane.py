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
import time
import webbrowser
from collections.abc import Awaitable, Callable
from typing import Any

from nicegui import ui

from paper_pile.core.buffer import NoteBuffer, find_recoverable
from paper_pile.core.events import EventBus
from paper_pile.core.links import external_url
from paper_pile.core.recovery import RecoveryEntry, RecoveryStore
from paper_pile.core.tabs import TabList
from paper_pile.core.vault import Vault, VaultError
from paper_pile.gui.components.editor import Editor, Mode
from paper_pile.gui.components.tabs import TabBar

log = logging.getLogger("paper_pile.editor_pane")

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
        self._timer: asyncio.TimerHandle | None = None
        self._failure_toasted = False
        self._rendered: tuple[tuple[int, str], ...] = ()
        self._rendered_active: int | None = None
        self._tabbar: TabBar
        self._editor: Editor
        self._empty: ui.label
        self._host: ui.element  # holds dialogs and notifications

    # ---- building ------------------------------------------------------------------------

    def build(self) -> None:
        with ui.column().classes("pp-pane pp-center"):
            self._tabbar = TabBar(
                self.tabs,
                on_activate=self._activate,
                on_close=lambda tab_id: self._spawn(self.close_tab(tab_id)),
                on_move=self._move_tab,
            )
            self._tabbar.build()
            with ui.element("div").classes("pp-editor-area"):
                self._empty = ui.label("Open a note to start writing").classes("pp-muted pp-empty")
                self._editor = Editor(
                    mode=self.mode,
                    link_target="python" if self._native else "window",
                    on_link=lambda e: self._on_link(e.args),
                    on_change=lambda e: self._on_change(e.args),
                    on_blur=lambda e: self._on_flush(e.args),
                    on_save=lambda e: self._on_flush(e.args),
                ).classes("pp-fill")
                self._editor.set_visibility(False)
        self._host = ui.element("div")
        self.bus.subscribe("tree.open", lambda path: self._spawn(self.open(path)))
        self.bus.subscribe("vault.renamed", lambda old, new: self._on_renamed(old, new))
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
        self._refresh()
        self._notify_tabs()

    def toggle_mode(self) -> None:
        """Live Preview <-> Source. Same text and undo history; only the rendering changes."""
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
        self._drop_tab(tab_id)

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

    def _on_link(self, args: dict[str, Any]) -> None:
        """Ctrl/Cmd+click on a link. Web links open in the browser (here, in the native window;
        in web mode the page already opened them). Note and relative links come with P3.3."""
        href = str(args.get("href", ""))
        url = external_url(href)
        if url is None:
            self._toast("Opening notes by link comes with link navigation (P3.3).")
        elif self._native:
            try:
                webbrowser.open(url)
            except Exception:
                log.exception("could not open %s", url)
                self._toast("Could not open the link.", error=True)

    def _on_disconnect(self) -> None:
        self._cancel_timer()
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
            if buf.dirty and not self._save_buffer(buf, refresh=False):
                failed = True
        if failed:
            self._schedule_save(RETRY_AFTER_FAILURE_S)
        else:
            self._failure_toasted = False
        self._refresh()

    def _save_buffer(self, buf: NoteBuffer, *, refresh: bool = True) -> bool:
        ok = buf.save()
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
        return {i: b.dirty or bool(b.error) for i, b in self.buffers.items()}

    def _refresh(self) -> None:
        unsaved = self._unsaved()
        if self._structure_changed():
            self._tabbar.render(unsaved)
        else:
            self._tabbar.set_unsaved(unsaved)
        self._show_state()

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
        elif buf.error:
            self._on_state("Save failed", True)
        elif buf.dirty:
            self._on_state("Editing…", False)
        else:
            self._on_state("Saved", False)

    def _notify_tabs(self) -> None:
        active = self.tabs.active_tab
        self._on_tabs_changed(self.tabs.paths, active.path if active else None)

    # ---- the tree renamed / deleted notes ------------------------------------------------

    def _on_renamed(self, old: str, new: str) -> None:
        changed = self.tabs.rename_prefix(old, new)
        for tab in changed:
            self.buffers[tab.id].rename(tab.path)
            if tab.id == self.tabs.active:
                self._editor.set_path(tab.path)  # relative image URLs depend on the note's folder
        if changed:
            self._refresh()
            self._notify_tabs()

    def _on_deleted(self, path: str) -> None:
        for tab in self.tabs.under(path):
            buf = self.buffers.get(tab.id)
            if buf is not None:
                buf.discard()  # its note is in .trash now; saving would bring it back
            self._drop_tab(tab.id)

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
