"""Left pane: the file tree.

Rows are flat (indented by depth); a folder's children are listed only while it is expanded,
so big vaults stay cheap. Click / right-click / drop / selection box are captured by
``static/tree.js`` and arrive here as events; every file operation goes through
``core.vault.Vault``, which validates paths. Other parts of the app learn about changes
through the event bus:

  ``tree.open``      (path)              a note was clicked
  ``vault.renamed``  (old, new)          rename or move (a folder path covers its children)
  ``vault.deleted``  (path, trashed)     moved to ``.trash/``

The header above the tree has three buttons: search (swaps the tree for the most recently
changed notes, with a filter box), new folder (a dialog asking for the name and where to put
it) and new note (no questions asked: ``Untitled 1``, ``Untitled 2``, ... in the selected folder).

Several rows can be selected: Ctrl/Cmd+click toggles a row, Shift+click picks the range from the
last clicked row, and a drag that starts on blank tree space draws a selection box (Ctrl adds to
the selection). Dragging a selected row moves the whole selection; the context menu of a
selected row offers Delete / Add to chat for all of them.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from nicegui import background_tasks, ui

from paper_pile.core.events import EventBus
from paper_pile.core.fsutil import reveal_in_file_manager
from paper_pile.core.vault import TreeEntry, Vault, VaultError
from paper_pile.gui.icons import ico, icon_button, line_icon

log = logging.getLogger("paper_pile.tree")

INDENT_PX = 14
BASE_PAD_PX = 6  # rows are inset 6 px (rounded hover), so names line up with "Files"
MENU_W, MENU_H = 210, 250  # rough size, only used to keep the menu on screen
RECENT_SHOWN = 50  # notes listed in search mode
RECENT_SCANNED = 500  # notes the filter looks through
VAULT_ROOT = ""  # the location value that means "the vault itself"


class FileTree:
    def __init__(
        self,
        vault: Vault,
        bus: EventBus,
        *,
        can_reveal: bool,
        hidden: Callable[[], set[str]] = set,
    ) -> None:
        self.vault = vault
        self._hidden = hidden  # folders not shown (the app's own; Settings → General → Folders)
        self.bus = bus
        self.can_reveal = can_reveal
        self._expanded: set[str] = set()
        self._selected: str | None = None  # the last clicked row (anchor of Shift+click)
        self._picked: set[str] = set()  # every selected row
        self._rows: dict[str, ui.element] = {}
        self._searching = False
        self._filter = ""
        self._search_button: ui.button
        self._search_box: ui.input
        self._root: ui.element
        self._menu: ui.column
        self._host: ui.element  # holds dialogs and notifications

    # ---- building ------------------------------------------------------------------------

    def build(self) -> None:
        with ui.row().classes("pp-files-head items-center no-wrap"):
            ui.label("Files").classes("pp-pane-title")
            ui.space()
            self._search_button = icon_button("search", self.toggle_search, "Recent notes")
            icon_button("folder-plus", self.new_folder, "New folder")
            icon_button("file-plus", self.new_note, "New note")
        self._search_box = (
            ui.input(placeholder="Filter recent notes")
            .props("outlined dense clearable debounce=150")
            .classes("pp-files-search")
        )
        self._search_box.on_value_change(lambda e: self._set_filter(e.value))
        self._search_box.set_visibility(False)
        self._root = ui.element("div").classes("pp-tree")
        with ui.teleport("body"):  # outside the splitter panels, which would clip/overlap it
            self._menu = ui.column().classes("pp-ctxmenu")
        self._host = ui.element("div").classes("pp-host")  # dialogs + toasts; takes no space
        ui.on("pp_tree_click", lambda e: self._guard(self._on_click(e.args)))
        ui.on("pp_tree_context", lambda e: self._guard(self._on_context(e.args)))
        ui.on("pp_tree_move", lambda e: self._guard(self._on_move(e.args)))
        ui.on("pp_tree_band", lambda e: self._guard(self._on_band(e.args)))
        ui.on("pp_ctx_close", lambda _e: self._close_menu())
        # the note menu (⋯) moves notes through the tree, like a drag would
        self.bus.subscribe(
            "note.move",
            lambda path, folder: background_tasks.create(
                self._guard(self._on_move({"src": path, "dst": folder}))
            ),
        )
        self.refresh()

    def refresh(self) -> None:
        """Re-list every expanded folder from disk (also used after external changes)."""
        self._rows.clear()
        self._root.clear()
        with self._root:
            if self._searching:
                count = self._render_recent()
                empty = "No notes match." if self._filter.strip() else "No notes yet."
            else:
                count = self._render_folder("", 0)
                empty = "No notes yet. Use the buttons above to create one."
            if count == 0:
                ui.label(empty).classes("pp-muted pp-tree-empty")
        self._apply_selection()

    # ---- search: recent notes ------------------------------------------------------------

    def new_note(self) -> Awaitable[None]:
        return self._guard(self._new_note())

    def new_folder(self) -> Awaitable[None]:
        return self._guard(self._new_folder())

    def show_search(self) -> None:
        """Make sure search mode is on (the folded-pane ribbon uses this)."""
        if not self._searching:
            self.toggle_search()

    def toggle_search(self) -> None:
        self._searching = not self._searching
        self._search_box.set_visibility(self._searching)
        if self._searching:
            self._search_button.classes("pp-icon-active")
            self._search_box.run_method("focus")
        else:
            self._search_button.classes(remove="pp-icon-active")
        self.refresh()

    def _set_filter(self, value: str | None) -> None:
        self._filter = value or ""
        if self._searching:
            self.refresh()

    def _render_recent(self) -> int:
        needle = self._filter.strip().lower()
        paths = [p for p in self.vault.recent_notes(RECENT_SCANNED) if needle in p.lower()]
        for path in paths[:RECENT_SHOWN]:
            self._recent_row(path)
        return min(len(paths), RECENT_SHOWN)

    def _recent_row(self, path: str) -> None:
        folder, _, name = path.rpartition("/")
        row = ui.element("div").classes("pp-tree-row")
        row._props["data-path"] = path
        row._props["data-dir"] = "0"
        row.style(f"padding-left: {BASE_PAD_PX}px")
        with row:
            line_icon("file-text").classes("pp-ico pp-ico-note")
            ui.label(name).classes("pp-tree-name")
            if folder:
                ui.label(folder).classes("pp-muted pp-tree-sub")
        self._rows[path] = row

    def _render_folder(self, rel: str, depth: int) -> int:
        try:
            entries = self.vault.list_tree(rel)
        except VaultError:
            self._expanded.discard(rel)  # the folder vanished underneath us
            return 0
        hidden = self._hidden()
        entries = [e for e in entries if e.path not in hidden]
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
                chevron = "chevron-down" if entry.path in self._expanded else "chevron-right"
                line_icon(chevron, "s").classes("pp-ico-chev")
                line_icon("folder").classes("pp-ico pp-ico-folder")
            else:
                ui.element("span").classes("pp-ico pp-ico-chev")  # aligns notes
                line_icon("file-text").classes("pp-ico pp-ico-note")
            ui.label(entry.name).classes("pp-tree-name")
        self._rows[entry.path] = row

    def _apply_selection(self) -> None:
        self._picked &= self._rows.keys()  # rows no longer shown (collapsed, gone) drop out
        for path, row in self._rows.items():
            if path in self._picked:
                row.classes("pp-tree-selected")
            else:
                row.classes(remove="pp-tree-selected")

    def _select(self, path: str | None) -> None:
        """Select just this row (or nothing)."""
        self._selected = path
        self._picked = set() if path is None else {path}
        self._apply_selection()

    def _pick_range(self, path: str, *, add: bool) -> None:
        """Shift+click: every shown row from the anchor to ``path`` (the anchor stays)."""
        order = list(self._rows)  # render order
        a, b = sorted((order.index(self._selected or path), order.index(path)))
        span = set(order[a : b + 1])
        self._picked = self._picked | span if add else span
        self._apply_selection()

    def _selection(self) -> list[str]:
        """The selected rows in render order, without rows inside a selected folder."""
        picked = [p for p in self._rows if p in self._picked]
        return [p for p in picked if not any(p.startswith(q + "/") for q in picked)]

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
        if args.get("range") and path in self._rows and self._selected in self._rows:
            self._pick_range(path, add=bool(args.get("toggle")))
            return
        if args.get("toggle"):
            self._picked ^= {path}
            self._selected = path
            self._apply_selection()
            return
        self._select(path)
        if args["isDir"]:
            self._expanded.symmetric_difference_update({path})
            self.refresh()
        else:
            self.bus.publish("tree.open", path=path)

    async def _on_band(self, args: dict[str, Any]) -> None:
        """The selection box was let go over ``paths`` (none: a click on blank space)."""
        self._close_menu()
        paths = [str(p) for p in args["paths"] if str(p) in self._rows]
        if args.get("add"):
            self._picked |= set(paths)
        else:
            self._picked = set(paths)
            self._selected = None
        if paths:
            self._selected = paths[-1]
        self._apply_selection()

    async def _on_context(self, args: dict[str, Any]) -> None:
        path, on_row, is_dir = str(args["path"]), bool(args["onRow"]), bool(args["isDir"])
        if on_row and path in self._picked and len(self._picked) > 1:
            self._open_menu(args, self._group_menu)
            return
        if on_row:
            self._select(path)
        self._open_menu(args, lambda: self._row_menu(path, on_row, is_dir))

    def _open_menu(self, args: dict[str, Any], fill: Callable[[], None]) -> None:
        self._menu.clear()
        with self._menu:
            fill()
        x = max(0, min(int(args["x"]), int(args["vw"]) - MENU_W))
        y = max(0, min(int(args["y"]), int(args["vh"]) - MENU_H))
        self._menu.style(f"left: {x}px; top: {y}px")
        self._menu.classes("pp-ctxmenu-open")

    def _group_menu(self) -> None:
        paths = self._selection()
        notes = [p for p in paths if self.vault.resolve(p).is_file()]
        if notes:
            label = "Add to chat" if len(notes) == 1 else f"Add {len(notes)} notes to chat"
            self._item(label, "messages-square", lambda: self._add_to_chat(*notes))
        self._item(
            f"Delete {len(paths)} items", "trash-2", lambda: self._delete(*paths), danger=True
        )

    def _row_menu(self, path: str, on_row: bool, is_dir: bool) -> None:
        if is_dir:
            folder = path if on_row else ""
            self._item("New note", "file-plus", lambda: self._new_note(folder))
            self._item("New folder", "folder-plus", lambda: self._new_folder(folder))
        if on_row and not is_dir:
            self._item("Add to chat", "messages-square", lambda: self._add_to_chat(path))
        if on_row:
            self._item("Rename", "square-pen", lambda: self._rename(path))
            self._item("Duplicate", "copy", lambda: self._duplicate(path))
            self._item("Delete", "trash-2", lambda: self._delete(path), danger=True)
            if self.can_reveal:
                self._item(
                    "Reveal in file manager",
                    "folder-open",
                    lambda: self._reveal(path),
                )

    async def _add_to_chat(self, *paths: str) -> None:
        for path in paths:
            self.bus.publish("tree.add_to_chat", path=path)

    def _item(
        self, label: str, icon: str, action: Callable[[], Awaitable[None]], *, danger: bool = False
    ) -> None:
        async def run() -> None:
            self._close_menu()
            await self._guard(action())

        # color=None: no Quasar colour class, so our CSS decides (layered !important rules win)
        button = ui.button(label, icon=ico(icon), on_click=run, color=None)
        button.props("flat dense no-caps align=left").classes("pp-ctx-item")
        if danger:
            button.classes("pp-ctx-danger")

    def _close_menu(self) -> None:
        self._menu.classes(remove="pp-ctxmenu-open")

    # ---- operations ----------------------------------------------------------------------

    def _reveal_and_select(self, path: str) -> None:
        parts = path.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            self._expanded.add("/".join(parts[:i]))
        self._selected = path
        self._picked = {path}
        self.refresh()

    def _target_folder(self) -> str:
        """Where a new note goes: the selected folder, a selected note's folder, else the vault."""
        sel = self._selected
        if sel is None:
            return VAULT_ROOT
        try:
            if self.vault.resolve(sel).is_dir():
                return sel
        except VaultError:
            return VAULT_ROOT
        return sel.rpartition("/")[0]

    async def _new_note(self, folder: str | None = None) -> None:
        """Create ``Untitled N`` right away (rename it from the tree or the title later)."""
        where = self._target_folder() if folder is None else folder
        name = self.vault.free_numbered_name(where, "Untitled", ".md")
        path = self.vault.create_note_in(where, name)
        self._reveal_and_select(path)
        self.bus.publish("tree.open", path=path)

    async def _new_folder(self, folder: str | None = None) -> None:
        """Ask for a name and a location (the vault unless one was chosen or right-clicked)."""
        picked = await self._folder_dialog(VAULT_ROOT if folder is None else folder)
        if picked is None:
            return
        where, name = picked
        self._reveal_and_select(self.vault.create_folder_in(where, name))

    async def _rename(self, path: str) -> None:
        current = path.rsplit("/", 1)[-1]
        shown = current.rsplit(".", 1)[0] if self.vault.resolve(path).is_file() else current
        name = await self._prompt("Rename", shown)
        if name is None or name.strip() == shown:
            return
        self._renamed((path, self.vault.rename_in_place(path, name)))

    async def _duplicate(self, path: str) -> None:
        self._reveal_and_select(self.vault.duplicate(path))

    async def _delete(self, *paths: str) -> None:
        names = [p.rsplit("/", 1)[-1] for p in paths]
        label = f"“{names[0]}”" if len(paths) == 1 else f"{len(paths)} items"
        if not await self._confirm(f"Move {label} to the trash?", "Delete"):
            return
        done: list[tuple[str, str]] = []
        failed: list[str] = []
        for path in paths:
            try:
                done.append((path, self.vault.delete(path)))
            except VaultError as exc:
                failed.append(str(exc))
                continue

            def gone(p: str, path: str = path) -> bool:
                return p == path or p.startswith(path + "/")

            self._expanded = {p for p in self._expanded if not gone(p)}
            self._picked = {p for p in self._picked if not gone(p)}
            if self._selected and gone(self._selected):
                self._selected = None
        self.refresh()
        for path, trashed in done:
            self.bus.publish("vault.deleted", path=path, trashed=trashed)
        if failed:
            self._error(failed[0])
        elif done:
            self._info(f"Moved to trash: {names[0] if len(done) == 1 else label}")

    async def _reveal(self, path: str) -> None:
        reveal_in_file_manager(self.vault.resolve(path))

    async def _on_move(self, args: dict[str, Any]) -> None:
        """A drop: ``src`` is one dragged row, ``srcs`` the dragged selection."""
        dst = str(args["dst"])
        srcs = [str(p) for p in args.get("srcs") or [args["src"]]]
        srcs = [s for s in srcs if not any(s.startswith(o + "/") for o in srcs)]
        moves: list[tuple[str, str]] = []
        failed: list[str] = []
        for src in srcs:
            if len(srcs) > 1 and (dst == src or dst.startswith(src + "/")):
                continue  # the drop folder is part of the selection: leave it where it is
            try:
                new = self.vault.move_into(src, dst)
            except VaultError as exc:
                failed.append(str(exc))
                continue
            if new != src:
                moves.append((src, new))
        if moves:
            if dst:
                self._expanded.add(dst)
            self._renamed(*moves)
        if failed:
            raise VaultError(failed[0])

    def _renamed(self, *moves: tuple[str, str]) -> None:
        """Notes or folders were renamed/moved (``old``, ``new``); the moved rows stay selected."""

        def rewrite(p: str) -> str:
            for old, new in moves:
                if p == old or p.startswith(old + "/"):
                    return new + p[len(old) :]
            return p

        self._expanded = {rewrite(p) for p in self._expanded}
        if len(moves) == 1:
            self._selected, self._picked = moves[0][1], {moves[0][1]}
        else:
            self._picked = {rewrite(p) for p in self._picked} | {new for _old, new in moves}
            self._selected = rewrite(self._selected) if self._selected else None
        self.refresh()
        for old, new in moves:
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

    async def _folder_dialog(self, folder: str) -> tuple[str, str] | None:
        options = {VAULT_ROOT: "Vault (top level)"} | {f: f for f in self.vault.folders()}
        with self._host, ui.dialog() as dialog, ui.card().classes("pp-dialog"):
            ui.label("New folder").classes("pp-dialog-title")
            field = ui.input("Name").props("outlined dense autofocus").classes("w-full")
            field.on_value_change(lambda _e: field.props(remove="error"))
            where = (
                ui.select(
                    options,
                    value=folder if folder in options else VAULT_ROOT,
                    label="Location",
                    with_input=True,
                )
                .props("outlined dense")
                .classes("w-full")
            )

            def submit() -> None:
                name = (field.value or "").strip()
                if not name:
                    field.props('error error-message="Enter a folder name"')
                    return
                dialog.submit((where.value or VAULT_ROOT, name))

            field.on("keydown.enter", submit)
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
                ui.button("Create", on_click=submit).props("no-caps")
        result = await dialog
        dialog.delete()
        return None if result is None else (str(result[0]), str(result[1]))

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
