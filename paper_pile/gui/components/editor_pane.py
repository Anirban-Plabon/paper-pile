"""Center pane: the editor for the open note, its autosave and its crash recovery.

The browser owns the live text; this pane keeps a :class:`~paper_pile.core.buffer.NoteBuffer`
in step with it and decides *when* to save (the buffer decides *what* happens):

  * ~1 s after the last keystroke (the editor reports changes 0.3 s after typing stops, then a
    0.7 s timer runs), immediately on blur, Ctrl+S, switching notes, and when the page closes;
  * a failed save keeps the text dirty and recoverable and is retried every few seconds.

Switching notes bumps a document id; events tagged with an older id are ignored, so a late
``change`` can never be written into the wrong note.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from nicegui import ui

from paper_pile.core.buffer import NoteBuffer, find_recoverable
from paper_pile.core.events import EventBus
from paper_pile.core.recovery import RecoveryEntry, RecoveryStore
from paper_pile.core.vault import Vault, VaultError
from paper_pile.gui.components.editor import Editor

log = logging.getLogger("paper_pile.editor_pane")

AUTOSAVE_AFTER_CHANGE_S = 0.7  # on top of the editor's own 0.3 s debounce: ~1 s in total
RETRY_AFTER_FAILURE_S = 5.0


class EditorPane:
    def __init__(
        self,
        vault: Vault,
        bus: EventBus,
        on_state: Callable[[str, bool], None] = lambda text, error: None,
    ) -> None:
        self.vault = vault
        self.bus = bus
        self.recovery = RecoveryStore(vault.root)
        self._on_state = on_state
        self.buffer: NoteBuffer | None = None
        self._doc_id = 0
        self._timer: asyncio.TimerHandle | None = None
        self._failure_toasted = False
        self._editor: Editor
        self._empty: ui.label
        self._host: ui.element  # holds dialogs and notifications

    # ---- building ------------------------------------------------------------------------

    def build(self) -> None:
        with ui.column().classes("pp-pane pp-center"):
            self._empty = ui.label("Open a note to start writing").classes("pp-muted pp-empty")
            self._editor = Editor(
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
        self._spawn(self._offer_startup_recovery())

    def _spawn(self, work: Awaitable[None]) -> None:
        async def guarded() -> None:
            try:
                await work
            except Exception:
                log.exception("editor pane action failed")
                self._toast("Something went wrong; see the log.", error=True)

        asyncio.get_running_loop().create_task(guarded())

    # ---- opening and switching -----------------------------------------------------------

    async def open(
        self, path: str, *, recovered: str | None = None, skip_recovery: bool = False
    ) -> None:
        if self.buffer is not None and self.buffer.path == path and recovered is None:
            self._editor.focus()
            return
        if recovered is None and not skip_recovery:
            entry = self.recovery.get(path)
            if entry is not None and self._differs_from_disk(entry):
                self._ask_recovery([entry], then_open=path)
                return
        try:
            new = NoteBuffer.open(self.vault, self.recovery, path, recovered=recovered)
        except VaultError as exc:
            self._toast(str(exc), error=True)  # the current note stays open
            return
        await self._leave_current()
        self.buffer = new
        self._doc_id += 1
        self._empty.set_visibility(False)
        self._editor.set_visibility(True)
        self._editor.set_text(new.text, self._doc_id)
        self._editor.focus()
        self._show_state()
        if new.dirty:  # restored text: the editor reports no change for it, so schedule the save
            self._schedule_save(AUTOSAVE_AFTER_CHANGE_S)

    def _differs_from_disk(self, entry: RecoveryEntry) -> bool:
        try:
            return self.vault.read_text(entry.path) != entry.text
        except VaultError:
            return True

    async def _leave_current(self) -> None:
        """Save the open note (pulling the freshest text from the browser) and let go of it."""
        buf = self.buffer
        if buf is None:
            return
        self._cancel_timer()
        text = await self._editor.get_text()
        if text is not None:
            buf.set_text(text)
        if not buf.save():
            self._toast(
                f"Could not save {buf.path}: {buf.error}. The text is kept for recovery.",
                error=True,
            )
        self.buffer = None

    # ---- events from the editor ----------------------------------------------------------

    def _on_change(self, args: dict[str, Any]) -> None:
        buf = self.buffer
        if buf is None or args.get("docId") != self._doc_id:
            return  # a late event from a note that is no longer shown
        buf.set_text(str(args["text"]))
        self._show_state()
        self._schedule_save(AUTOSAVE_AFTER_CHANGE_S)

    def _on_flush(self, args: dict[str, Any]) -> None:
        """Blur / Ctrl+S: take the text and save right now."""
        buf = self.buffer
        if buf is None or args.get("docId") != self._doc_id:
            return
        buf.set_text(str(args["text"]))
        self._save_now()

    def _on_disconnect(self) -> None:
        if self.buffer is not None:
            self._cancel_timer()
            self.buffer.save()

    # ---- saving --------------------------------------------------------------------------

    def _schedule_save(self, delay: float) -> None:
        self._cancel_timer()
        self._timer = asyncio.get_running_loop().call_later(delay, self._save_now)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _save_now(self) -> None:
        self._cancel_timer()
        buf = self.buffer
        if buf is None:
            return
        if buf.save():
            self._failure_toasted = False
        else:
            if not self._failure_toasted:
                self._failure_toasted = True
                self._toast(f"Could not save {buf.path}: {buf.error}", error=True)
            self._schedule_save(RETRY_AFTER_FAILURE_S)
        self._show_state()

    def _show_state(self) -> None:
        buf = self.buffer
        if buf is None:
            self._on_state("Ready", False)
        elif buf.error:
            self._on_state("Save failed", True)
        elif buf.dirty:
            self._on_state("Editing…", False)
        else:
            self._on_state("Saved", False)

    # ---- the tree renamed / deleted the open note ----------------------------------------

    def _on_renamed(self, old: str, new: str) -> None:
        buf = self.buffer
        if buf is not None and (buf.path == old or buf.path.startswith(old + "/")):
            buf.rename(new + buf.path[len(old) :])

    def _on_deleted(self, path: str) -> None:
        buf = self.buffer
        if buf is None or not (buf.path == path or buf.path.startswith(path + "/")):
            return
        self._cancel_timer()
        buf.discard()  # its note is in .trash now; saving would bring it back
        self.buffer = None
        self._doc_id += 1
        self._editor.set_visibility(False)
        self._empty.set_visibility(True)
        self._show_state()

    # ---- crash recovery ------------------------------------------------------------------

    async def _offer_startup_recovery(self) -> None:
        entries = find_recoverable(self.vault, self.recovery)
        if entries:
            self._ask_recovery(entries, then_open=None)

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
                    ui.button("Restore", on_click=lambda e=entry: self._restore(dialog, e)).props(
                        "dense no-caps"
                    )
                    ui.button(
                        "Discard", on_click=lambda e=entry: self._discard(dialog, e, then_open)
                    ).props("flat dense no-caps")
            ui.button("Later", on_click=lambda: self._later(dialog, then_open)).props(
                "flat no-caps"
            )
        dialog.open()

    def _restore(self, dialog: ui.dialog, entry: RecoveryEntry) -> None:
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
