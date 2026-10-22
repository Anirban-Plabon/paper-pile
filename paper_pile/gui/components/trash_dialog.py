"""The Trash popup (PLAN §4.18): what was deleted, newest first, each with *Restore*.

Listing and restoring are ``core.trash``; this only draws them. Nothing can be deleted for good
from here (the app never hard-deletes).
"""

from collections.abc import Callable
from datetime import datetime

from nicegui import ui

from paper_pile.core.trash import TrashItem, list_trash, restore
from paper_pile.core.vault import Vault, VaultError
from paper_pile.gui.icons import close_button, line_icon


def when(deleted: datetime | None, now: datetime) -> str:
    if deleted is None:
        return ""
    if deleted.date() == now.date():
        return f"Today {deleted:%H:%M}"
    if deleted.year == now.year:
        return f"{deleted:%d %b, %H:%M}"
    return f"{deleted:%d %b %Y}"


class TrashDialog:
    def __init__(self, vault: Vault, host: ui.element, on_restored: Callable[[str], None]) -> None:
        self.vault = vault
        self._host = host  # the popup lives here (not in the menu that opened it)
        self._on_restored = on_restored  # (new path) the tree, index, calendar catch up
        self._filter = ""
        self._list: ui.column

    async def open(self) -> None:
        with self._host, ui.dialog() as dialog, ui.card().classes("pp-dialog pp-trash"):
            with ui.row().classes("items-center no-wrap w-full"):
                ui.label("Trash").classes("pp-dialog-title")
                ui.space()
                close_button(dialog.close)
            ui.label("Restore puts a note or folder back where it was.").classes("pp-muted")
            search = ui.input(placeholder="Filter").props("outlined dense clearable")
            search.classes("w-full").on_value_change(lambda e: self._set_filter(e.value))
            self._list = ui.column().classes("pp-trash-list")
        self._fill()
        dialog.open()
        await dialog
        dialog.delete()

    def _set_filter(self, value: str | None) -> None:
        self._filter = (value or "").strip().lower()
        self._fill()

    def _fill(self) -> None:
        items = [i for i in list_trash(self.vault) if self._filter in i.path.lower()]
        now = datetime.now()
        self._list.clear()
        with self._list:
            if not items:
                empty = "Nothing matches." if self._filter else "The trash is empty."
                ui.label(empty).classes("pp-muted pp-trash-none")
            for item in items:
                folder = item.path.rpartition("/")[0]
                with ui.row().classes("pp-trash-row items-center no-wrap"):
                    line_icon("folder" if item.is_dir else "file-text").classes("pp-ico")
                    with ui.column().classes("pp-trash-text"):
                        ui.label(item.name).classes("pp-trash-name")
                        detail = " · ".join(x for x in (folder, when(item.deleted, now)) if x)
                        ui.label(detail).classes("pp-muted pp-trash-sub")
                    ui.button(
                        "Restore", on_click=lambda _e, i=item: self._restore(i), color=None
                    ).props("flat dense no-caps").classes("pp-trash-restore")

    def _restore(self, item: TrashItem) -> None:
        try:
            path = restore(self.vault, item)
        except (VaultError, OSError) as exc:
            ui.notify(f"Could not restore {item.name}: {exc}", type="negative")
            self._fill()
            return
        moved = "" if path == item.path else f" as {path.rpartition('/')[2]}"
        ui.notify(f"Restored {item.name}{moved}")
        self._fill()
        self._on_restored(path)
