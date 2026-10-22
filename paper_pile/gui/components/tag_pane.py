"""The ``#tag`` tab of the right pane (PLAN §4.16): every note with the tag (or a tag nested in
it), from the index. Clicking a note offers Open / Open in split."""

from collections.abc import Awaitable, Callable

from nicegui import background_tasks, ui

from paper_pile.core.index import Index, TaggedNote
from paper_pile.core.tags import norm_tag
from paper_pile.gui.icons import line_icon


class TagPane:
    def __init__(
        self,
        index: Index,
        open_note: Callable[[str], Awaitable[None]],
        open_in_split: Callable[[str], Awaitable[None]],
    ) -> None:
        self._index = index
        self._open_note = open_note
        self._open_in_split = open_in_split
        self.tag = ""
        self._shown: list[TaggedNote] | None = None
        self._title: ui.label
        self._count: ui.label
        self._list: ui.column

    def build(self) -> None:
        with ui.column().classes("pp-tagpane"):
            with ui.row().classes("pp-tagpane-head items-center no-wrap"):
                self._title = ui.label("").classes("pp-tag pp-tagpane-tag")
                self._count = ui.label("").classes("pp-muted pp-tagpane-count")
            self._list = ui.column().classes("pp-tagpane-list")

    def show(self, tag: str) -> None:
        self.tag = tag.lstrip("#")
        self._shown = None
        self.refresh()

    def refresh(self) -> None:
        """Re-read the list; only redraws when it changed (it is called after every save)."""
        if not self.tag:
            return
        notes = self._index.notes_with_tag(self.tag)
        if notes == self._shown:
            return
        self._shown = notes
        self._title.set_text(f"#{self.tag}")
        self._count.set_text(f"{len(notes)} note" + ("" if len(notes) == 1 else "s"))
        self._list.clear()
        with self._list:
            if not notes:
                ui.label("No notes have this tag.").classes("pp-muted pp-tagpane-empty")
            for note in notes:
                self._row(note)

    def _row(self, note: TaggedNote) -> None:
        folder = note.path.rpartition("/")[0]
        nested = [t for t in note.tags if norm_tag(t) != norm_tag(self.tag)]
        with ui.row().classes("pp-tagpane-row items-center no-wrap") as row:
            line_icon("file-text").classes("pp-tagpane-icon")
            with ui.column().classes("pp-tagpane-text"):
                ui.label(note.title).classes("pp-tagpane-title")
                detail = " · ".join(x for x in (folder, " ".join(f"#{t}" for t in nested)) if x)
                if detail:
                    ui.label(detail).classes("pp-muted pp-tagpane-detail")
            with ui.menu().props('anchor="bottom left" self="top left"').classes("pp-note-menu"):
                self._item("file-text", "Open", lambda p=note.path: self._open_note(p))
                self._item("columns-2", "Open in split", lambda p=note.path: self._open_in_split(p))
        row.mark(note.path)

    def _item(self, icon: str, label: str, run: Callable[[], Awaitable[None]]) -> None:
        item = ui.menu_item(on_click=lambda: background_tasks.create(run()))
        item.classes("pp-note-menu-item").mark(label)
        with item:
            line_icon(icon).classes("pp-note-menu-icon")
            ui.label(label).classes("pp-note-menu-label")
