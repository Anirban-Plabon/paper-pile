"""Settings → AI → Memories: browse, read and delete the vault's saved chats.

Shows the memories folder (changeable: ``ai.chats_folder``; the chats can move along), a search
box and a date range (a calendar popup) that filter the list, one line per chat (title and day;
the first 10, then *Show all*), and bulk deletes (the shown ones, or all). A click opens it as a
rendered markdown document with *Open in chat*, *Copy as Markdown*, *Save as note* and *Delete*.
Every delete moves files to ``<vault>/.trash/`` (:mod:`paper_pile.core.ai.chats`).
"""

import json
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

from nicegui import ui

from paper_pile.core.ai.chats import (
    SavedChat,
    chat_day,
    chat_markdown,
    chat_note_name,
    delete_chats,
    filter_chats,
    list_chats,
    move_chats,
)
from paper_pile.core.parser import render_chat_html
from paper_pile.core.vault import ExistsError, InvalidPathError, Vault
from paper_pile.gui.components.vault_dialog import ask_folder
from paper_pile.gui.dialog import Dialog
from paper_pile.gui.icons import close_button, icon_button, line_icon
from paper_pile.gui.tips import tip

log = logging.getLogger("paper_pile.memories")

SHOWN_FIRST = 10  # rows before "Show all"


def _day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


class MemoriesPanel:
    def __init__(
        self,
        vault: Vault,
        folder: Callable[[], Path],
        set_folder: Callable[[str], bool] = lambda _value: False,
        native: bool = False,
        open_chat: Callable[[str], bool] = lambda _id: False,
        chats_deleted: Callable[[set[str]], None] = lambda _ids: None,
        open_note: Callable[[str], None] = lambda _path: None,
        user_name: Callable[[], str] = lambda: "",
    ) -> None:
        self.vault = vault
        self._folder = folder
        self._set_folder = set_folder
        self._native = native
        self._open_chat = open_chat
        self._deleted = chats_deleted
        self._open_note = open_note
        self._user_name = user_name
        self.query = ""
        self.start: date | None = None
        self.end: date | None = None
        self._all = False  # "Show all" pressed
        self._chats: list[SavedChat] = []
        self._root: ui.column
        self._list: ui.column
        self._count: ui.label
        self._delete_shown: ui.button
        self._more: ui.button

    # ---- building --------------------------------------------------------------------------

    def build(self) -> None:
        """Draw the panel where the caller is: under the Memories settings of the AI page."""
        self.query, self.start, self.end, self._all = "", None, None, False
        self._location()
        with ui.column().classes("pp-mem") as self._root:
            with ui.row().classes("pp-mem-filters items-center no-wrap"):
                search = ui.input(placeholder="Filter memories", on_change=self._searched)
                search.props("dense outlined clearable").classes("pp-mem-search")
                with search.add_slot("prepend"):
                    line_icon("search").classes("pp-set-search-icon")
                self._date_field("From", lambda d: setattr(self, "start", d))
                self._date_field("To", lambda d: setattr(self, "end", d))
            with ui.row().classes("pp-mem-bar items-center no-wrap"):
                self._count = ui.label("").classes("pp-muted pp-mem-count")
                ui.space()
                self._delete_shown = ui.button(
                    "Delete shown", on_click=self._delete_filtered, color=None
                ).props("flat dense no-caps")
                self._delete_shown.classes("pp-mem-del")
                delete_all = ui.button("Delete all", on_click=self._delete_all, color=None)
                delete_all.props("flat dense no-caps").classes("pp-mem-del")
            self._list = ui.column().classes("pp-mem-list")
            self._more = ui.button(on_click=self._toggle_all, color=None)
            self._more.props("flat dense no-caps").classes("pp-mem-more")
        self.reload()

    @ui.refreshable_method
    def _location(self) -> None:
        folder = self._folder()
        with ui.row().classes("pp-set-row items-center"):
            with ui.column().classes("pp-set-text"):
                ui.label("Memories folder").classes("pp-set-label")
                tip(ui.label(str(folder)).classes("pp-set-help pp-mem-path"), str(folder))
            with ui.row().classes("pp-set-control items-center no-wrap"):
                icon_button("copy", lambda: self._copy(str(folder), "Path copied"), "Copy path")
                ui.button("Change", on_click=self._change_folder, color=None).props(
                    "flat dense no-caps"
                ).classes("pp-mem-change")

    async def _change_folder(self) -> None:
        """Pick another folder; offer to move the chats that are in the old one."""
        old = self._folder()
        start = old if old.is_dir() else self.vault.root
        picked = await ask_folder(start, native=self._native, title="Memories folder", action="Use")
        if picked is None or picked.resolve() == old.resolve():
            return
        try:  # inside the vault: kept vault-relative, so the vault can move
            value = picked.resolve().relative_to(self.vault.root.resolve()).as_posix()
        except ValueError:
            value = str(picked)
        count = len(list_chats(old))
        if not self._set_folder(value):
            return
        if count and await self._ask_move(count, picked):
            moved = move_chats(old, picked)
            ui.notify(f"{moved} memories moved", timeout=1500, position="bottom")
        self._location.refresh()
        self.reload()

    async def _ask_move(self, count: int, to: Path) -> bool:
        with self._root, Dialog() as dialog, ui.card().classes("pp-dialog"):
            ui.label(f"Move {count} memories?").classes("pp-dialog-title")
            ui.label(f"Move the saved chats to {to}, or leave them where they are.").classes(
                "pp-muted pp-dialog-text"
            )
            with ui.row().classes("justify-end w-full"):
                ui.button("Leave them", on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button("Move", on_click=lambda: dialog.submit(True)).props("no-caps unelevated")
        result = await dialog
        dialog.delete()
        return bool(result)

    def _date_field(self, label: str, store: Callable[[date | None], None]) -> None:
        """A date box with our own calendar popup (the browser's date input is not themed)."""

        def changed(value: str | None) -> None:
            store(_day(value))
            self._render()

        field = ui.input(label=label, placeholder="YYYY-MM-DD")
        field.props("dense outlined clearable stack-label").classes("pp-mem-date")
        with field.add_slot("append"):
            icon = line_icon("calendar", "s").classes("pp-mem-cal")
        with field:
            menu = ui.menu().props('no-parent-event anchor="bottom right" self="top right"')
            menu.classes("pp-date-popup")
            with menu:
                picker = ui.date(mask="YYYY-MM-DD").props("minimal flat").classes("pp-date")
        picker.bind_value(field)
        picker.on_value_change(lambda _e: menu.close())
        field.on_value_change(lambda e: changed(e.value))
        icon.on("click", menu.open)
        field.on("click", menu.open)

    def _searched(self, e: object) -> None:
        self.query = str(getattr(e, "value", "") or "").strip()
        self._render()

    # ---- the list --------------------------------------------------------------------------

    def reload(self) -> None:
        """Read the chats from disk again and redraw the list."""
        self._chats = list_chats(self._folder())
        self._render()

    def _toggle_all(self) -> None:
        self._all = not self._all
        self._render()

    def _shown(self) -> list[SavedChat]:
        return filter_chats(self._chats, self.query, self.start, self.end)

    def _render(self) -> None:
        if self._list.is_deleted:
            return
        shown = self._shown()
        total = len(self._chats)
        filtered = bool(self.query or self.start or self.end)
        self._count.set_text(
            f"{len(shown)} of {total} memories" if filtered else f"{total} memories"
        )
        self._delete_shown.set_text(f"Delete shown ({len(shown)})")
        self._delete_shown.set_visibility(filtered and bool(shown))
        self._list.clear()
        with self._list:
            if not shown:
                text = "No memories match." if filtered and total else "No saved chats yet."
                ui.label(text).classes("pp-muted pp-mem-empty")
            for chat in shown if self._all else shown[:SHOWN_FIRST]:
                self._row(chat)
        hidden = len(shown) - SHOWN_FIRST
        self._more.set_text("Show less" if self._all else f"Show all ({len(shown)})")
        self._more.set_visibility(hidden > 0)

    def _row(self, chat: SavedChat) -> None:
        row = ui.row().classes("pp-mem-row items-center no-wrap")
        with row:
            line_icon("message-square-text").classes("pp-mem-icon")
            ui.label(chat.title or "Untitled chat").classes("pp-mem-title")
            day = chat_day(chat)
            fmt = "%b %d" if day.year == date.today().year else "%b %d, %Y"
            ui.label(day.strftime(fmt).replace(" 0", " ")).classes("pp-muted pp-mem-day")
            remove = line_icon("trash-2", "s").classes("pp-mem-row-del")
            tip(remove, "Delete")
            remove.props("tabindex=0 role=button aria-label=Delete")  # reachable by Tab
            remove.on("click.stop", lambda _e, c=chat: self._delete([c]))
            remove.on("keydown.enter.stop", lambda _e, c=chat: self._delete([c]))
        row.on("click", lambda _e, c=chat: self._view(c))

    # ---- reading one -----------------------------------------------------------------------

    def _view(self, chat: SavedChat) -> None:
        text = chat_markdown(chat, self._user_name())
        with self._root, Dialog() as dialog, ui.card().classes("pp-dialog pp-mem-view"):
            with ui.row().classes("pp-mem-view-head items-center no-wrap"):
                ui.space()  # the document below starts with the title
                icon_button(
                    "message-square", lambda: self._to_chat(chat, dialog), "Open in chat", "m"
                )
                icon_button(
                    "copy", lambda: self._copy(text, "Copied as Markdown"), "Copy as Markdown", "m"
                )
                icon_button(
                    "file-plus",
                    lambda: self._save_note(chat, text, dialog),
                    "Save as note",
                    "m",
                )
                icon_button(
                    "trash-2",
                    lambda: self._delete([chat], dialog),
                    "Delete",
                    "m",
                )
                close_button(dialog.close)
            body = ui.html(render_chat_html(text), sanitize=False).classes("pp-msg-body pp-mem-doc")
        dialog.on("hide", lambda _e: dialog.delete())
        dialog.open()
        ui.run_javascript(
            f"setTimeout(() => window.ppTypeset && "
            f"window.ppTypeset(document.getElementById('c{body.id}')), 0)"
        )

    def _to_chat(self, chat: SavedChat, dialog: ui.dialog) -> None:
        if self._open_chat(chat.id):
            dialog.close()
        else:
            ui.notify("Wait for the current reply to finish.", type="warning")

    def _copy(self, text: str, message: str) -> None:
        ui.run_javascript(
            f"navigator.clipboard && navigator.clipboard.writeText({json.dumps(text)})"
        )
        ui.notify(message, timeout=1200, position="bottom")

    async def _save_note(self, chat: SavedChat, text: str, dialog: ui.dialog) -> None:
        """Write the chat into the vault root as a note (a free name) and open it."""
        name = chat_note_name(chat)
        try:
            if self.vault.exists(f"{name}.md"):
                name = self.vault.free_numbered_name("", name, ".md")
            path = self.vault.create_note_in("", name, text)
        except (ExistsError, InvalidPathError, OSError):
            log.exception("could not save chat %s as a note", chat.id)
            ui.notify("Could not save the chat as a note.", type="negative")
            return
        dialog.close()
        ui.notify(f"Saved as {path}", timeout=2000, position="bottom")
        self._open_note(path)

    # ---- deleting --------------------------------------------------------------------------

    async def _confirm(self, title: str, detail: str) -> bool:
        with self._root, Dialog() as dialog, ui.card().classes("pp-dialog"):
            ui.label(title).classes("pp-dialog-title")
            ui.label(detail).classes("pp-muted pp-dialog-text")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button("Move to trash", on_click=lambda: dialog.submit(True)).props(
                    "no-caps color=negative"
                )
        result = await dialog
        dialog.delete()
        return bool(result)

    async def _delete_filtered(self) -> None:
        shown = self._shown()
        if shown and await self._confirm(
            f"Delete {len(shown)} shown memories?",
            "Every chat that matches the filter moves to the vault's trash.",
        ):
            self._remove(shown)

    async def _delete_all(self) -> None:
        if self._chats and await self._confirm(
            f"Delete all {len(self._chats)} memories?",
            "Every saved chat of this vault moves to the vault's trash.",
        ):
            self._remove(self._chats)

    async def _delete(self, chats: list[SavedChat], dialog: ui.dialog | None = None) -> None:
        if len(chats) != 1 or await self._confirm(
            "Delete this memory?", f"“{chats[0].title}” moves to the vault's trash."
        ):
            if dialog is not None:
                dialog.close()
            self._remove(chats)

    def _remove(self, chats: list[SavedChat]) -> None:
        ids = {c.id for c in chats}
        moved = delete_chats(self.vault, self._folder(), ids)
        self._deleted(ids)
        self.reload()
        if moved < len(ids):
            ui.notify("Some chats could not be deleted.", type="negative")
        else:
            noun = "memory" if moved == 1 else "memories"
            ui.notify(f"{moved} {noun} moved to the trash", timeout=1500, position="bottom")
