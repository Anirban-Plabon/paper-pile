"""Left pane: the file tree.

Rows are flat (indented by depth); a folder's children are listed only while it is expanded,
so big vaults stay cheap. Click / right-click / drop are captured by ``static/tree.js`` and
arrive here as events; every file operation goes through ``core.vault.Vault``, which
validates paths. Other parts of the app learn about changes through the event bus:

  ``tree.open``      (path)              a note was clicked
  ``vault.renamed``  (old, new)          rename or move (a folder path covers its children)
  ``vault.deleted``  (path, trashed)     moved to ``.trash/``
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from nicegui import ui

from paper_pile.core.events import EventBus
from paper_pile.core.fsutil import reveal_in_file_manager
from paper_pile.core.vault import TreeEntry, Vault, VaultError, join_rel

log = logging.getLogger("paper_pile.tree")

INDENT_PX = 14
BASE_PAD_PX = 8
MENU_W, MENU_H = 210, 250  # rough size, only used to keep the menu on screen


class FileTree:
    def __init__(self, vault: Vault, bus: EventBus, *, can_reveal: bool) -> None:
        self.vault = vault
        self.bus = bus
        self.can_reveal = can_reveal
        self._expanded: set[str] = set()
        self._selected: str | None = None
        self._rows: dict[str, ui.element] = {}
        self._root: ui.element
        self._menu: ui.column
        self._host: ui.element  # holds dialogs and notifications

    # ---- building ------------------------------------------------------------------------

    def build(self) -> None:
        self._root = ui.element("div").classes("pp-tree")
        with ui.teleport("body"):  # outside the splitter panels, which would clip/overlap it
            self._menu = ui.column().classes("pp-ctxmenu")
        self._host = ui.element("div")
        ui.on("pp_tree_click", lambda e: self._guard(self._on_click(e.args)))
        ui.on("pp_tree_context", lambda e: self._guard(self._on_context(e.args)))
        ui.on("pp_tree_move", lambda e: self._guard(self._on_move(e.args)))
        ui.on("pp_ctx_close", lambda _e: self._close_menu())
        self.refresh()

    def refresh(self) -> None:
        """Re-list every expanded folder from disk (also used after external changes)."""
        self._rows.clear()
        self._root.clear()
        with self._root:
            count = self._render_folder("", 0)
            if count == 0:
                ui.label("No notes yet. Right-click to create one.").classes(
                    "pp-muted pp-tree-empty"
                )
        self._apply_selection()

    def _render_folder(self, rel: str, depth: int) -> int:
        try:
            entries = self.vault.list_tree(rel)
        except VaultError:
            self._expanded.discard(rel)  # the folder vanished underneath us
            return 0
        for entry in entries:
            self._row(entry, depth)
            if entry.is_dir and entry.path in self._expanded:
                self._render_folder(entry.path, depth + 1)
        return len(entries)

    def _row(self, entry: TreeEntry, depth: int) -> None:
        row = ui.element("div").classes("pp-tree-row")
        row._props["data-path"] = entry.path
        row._props["data-dir"] = "1" if entry.is_dir else "0"
        row._props["draggable"] = "true"
        row.style(f"padding-left: {BASE_PAD_PX + depth * INDENT_PX}px")
        with row:
            if entry.is_dir:
                chevron = (
                    "fa-solid fa-chevron-down"
                    if entry.path in self._expanded
                    else "fa-solid fa-chevron-right"
                )
                ui.icon(chevron).classes("pp-ico pp-ico-chev")
                ui.icon("fa-regular fa-folder").classes("pp-ico pp-ico-folder")
            else:
                ui.element("span").classes("pp-ico pp-ico-chev")  # aligns notes
                ui.icon("fa-regular fa-file-lines").classes("pp-ico pp-ico-note")
            ui.label(entry.name).classes("pp-tree-name")
        self._rows[entry.path] = row

    def _apply_selection(self) -> None:
        for path, row in self._rows.items():
            if path == self._selected:
                row.classes("pp-tree-selected")
            else:
                row.classes(remove="pp-tree-selected")

    def _select(self, path: str | None) -> None:
        self._selected = path
        self._apply_selection()

    # ---- events --------------------------------------------------------------------------

    async def _guard(self, work: Awaitable[None]) -> None:
        """Run a handler; a refused operation becomes a toast, never a crash."""
        try:
            await work
        except VaultError as exc:
            self._error(str(exc))
        except Exception:
            log.exception("file tree action failed")
            self._error("Something went wrong; see the log.")

    async def _on_click(self, args: dict[str, Any]) -> None:
        self._close_menu()
        path = str(args["path"])
        self._select(path)
        if args["isDir"]:
            self._expanded.symmetric_difference_update({path})
            self.refresh()
        else:
            self.bus.publish("tree.open", path=path)

    async def _on_context(self, args: dict[str, Any]) -> None:
        path, on_row, is_dir = str(args["path"]), bool(args["onRow"]), bool(args["isDir"])
        if on_row:
            self._select(path)
        self._menu.clear()
        with self._menu:
            if is_dir:
                folder = path if on_row else ""
                self._item(
                    "New note", "fa-solid fa-file-circle-plus", lambda: self._new_note(folder)
                )
                self._item(
                    "New folder", "fa-solid fa-folder-plus", lambda: self._new_folder(folder)
                )
            if on_row and not is_dir:
                self._item("Add to chat", "fa-regular fa-comments", lambda: self._add_to_chat(path))
            if on_row:
                self._item("Rename", "fa-regular fa-pen-to-square", lambda: self._rename(path))
                self._item("Duplicate", "fa-regular fa-copy", lambda: self._duplicate(path))
                self._item(
                    "Delete", "fa-regular fa-trash-can", lambda: self._delete(path), danger=True
                )
                if self.can_reveal:
                    self._item(
                        "Reveal in file manager",
                        "fa-regular fa-folder-open",
                        lambda: self._reveal(path),
                    )
        x = max(0, min(int(args["x"]), int(args["vw"]) - MENU_W))
        y = max(0, min(int(args["y"]), int(args["vh"]) - MENU_H))
        self._menu.style(f"left: {x}px; top: {y}px")
        self._menu.classes("pp-ctxmenu-open")

    async def _add_to_chat(self, path: str) -> None:
        self.bus.publish("tree.add_to_chat", path=path)

    def _item(
        self, label: str, icon: str, action: Callable[[], Awaitable[None]], *, danger: bool = False
    ) -> None:
        async def run() -> None:
            self._close_menu()
            await self._guard(action())

        # color=None: no Quasar colour class, so our CSS decides (layered !important rules win)
        button = ui.button(label, icon=icon, on_click=run, color=None)
        button.props("flat dense no-caps align=left").classes("pp-ctx-item")
        if danger:
            button.classes("pp-ctx-danger")

    def _close_menu(self) -> None:
        self._menu.classes(remove="pp-ctxmenu-open")

    # ---- operations ----------------------------------------------------------------------

    def _free_name(self, folder: str, base: str, suffix: str = "") -> str:
        name, n = base, 2
        while self.vault.resolve(join_rel(folder, name + suffix)).exists():
            name = f"{base} {n}"
            n += 1
        return name

    def _reveal_and_select(self, path: str) -> None:
        parts = path.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            self._expanded.add("/".join(parts[:i]))
        self._selected = path
        self.refresh()

    async def _new_note(self, folder: str) -> None:
        name = await self._prompt("New note", self._free_name(folder, "Untitled", ".md"))
        if name is None:
            return
        path = self.vault.create_note_in(folder, name)
        self._reveal_and_select(path)
        self.bus.publish("tree.open", path=path)

    async def _new_folder(self, folder: str) -> None:
        name = await self._prompt("New folder", self._free_name(folder, "New folder"))
        if name is None:
            return
        self._reveal_and_select(self.vault.create_folder_in(folder, name))

    async def _rename(self, path: str) -> None:
        current = path.rsplit("/", 1)[-1]
        shown = current.rsplit(".", 1)[0] if self.vault.resolve(path).is_file() else current
        name = await self._prompt("Rename", shown)
        if name is None or name.strip() == shown:
            return
        self._renamed(path, self.vault.rename_in_place(path, name))

    async def _duplicate(self, path: str) -> None:
        self._reveal_and_select(self.vault.duplicate(path))

    async def _delete(self, path: str) -> None:
        label = path.rsplit("/", 1)[-1]
        if not await self._confirm(f"Move “{label}” to the trash?", "Delete"):
            return
        trashed = self.vault.delete(path)
        self._expanded = {p for p in self._expanded if p != path and not p.startswith(path + "/")}
        if self._selected and (self._selected == path or self._selected.startswith(path + "/")):
            self._selected = None
        self.refresh()
        self.bus.publish("vault.deleted", path=path, trashed=trashed)
        self._info(f"Moved to trash: {label}")

    async def _reveal(self, path: str) -> None:
        reveal_in_file_manager(self.vault.resolve(path))

    async def _on_move(self, args: dict[str, Any]) -> None:
        src, dst = str(args["src"]), str(args["dst"])
        new = self.vault.move_into(src, dst)
        if new != src:
            if dst:
                self._expanded.add(dst)
            self._renamed(src, new)

    def _renamed(self, old: str, new: str) -> None:
        def rewrite(p: str) -> str:
            return new + p[len(old) :] if p == old or p.startswith(old + "/") else p

        self._expanded = {rewrite(p) for p in self._expanded}
        self._selected = new
        self.refresh()
        self.bus.publish("vault.renamed", old=old, new=new)

    # ---- dialogs and toasts --------------------------------------------------------------

    async def _prompt(self, title: str, value: str) -> str | None:
        with self._host, ui.dialog() as dialog, ui.card().classes("pp-dialog"):
            ui.label(title).classes("pp-dialog-title")
            field = ui.input(value=value).props("outlined dense autofocus").classes("w-full")
            field.on("keydown.enter", lambda: dialog.submit(field.value))
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
                ui.button("OK", on_click=lambda: dialog.submit(field.value)).props("no-caps")
        dialog.open()
        await asyncio.sleep(0.15)
        field.run_method("select")
        result = await dialog
        dialog.delete()
        return None if result is None else str(result)

    async def _confirm(self, message: str, ok_label: str) -> bool:
        with self._host, ui.dialog() as dialog, ui.card().classes("pp-dialog"):
            ui.label(message).classes("pp-dialog-title")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button(ok_label, on_click=lambda: dialog.submit(True)).props(
                    "no-caps color=negative"
                )
        result = await dialog
        dialog.delete()
        return bool(result)

    def _error(self, message: str) -> None:
        with self._host:
            ui.notify(message, type="negative")

    def _info(self, message: str) -> None:
        with self._host:
            ui.notify(message)
