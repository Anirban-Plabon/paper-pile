"""Backlinks pane under the editor: the notes that link to the open note, with the line of
each link. Collapsible. It only displays what :mod:`paper_pile.core.index` found."""

from collections.abc import Callable
from dataclasses import dataclass
from html import escape

from nicegui import ui

from paper_pile.core.snippets import Snippet


@dataclass(frozen=True, slots=True)
class BacklinkItem:
    path: str
    title: str
    line: int
    snippet: Snippet


class BacklinksPane:
    def __init__(self, on_open: Callable[[str, int], None]) -> None:
        self._on_open = on_open
        self._open = True
        self._items: list[BacklinkItem] = []
        self._root: ui.element
        self._icon: ui.icon
        self._title: ui.label
        self._body: ui.column

    def build(self) -> None:
        self._root = ui.column().classes("pp-backlinks")
        with self._root:
            with ui.row().classes("pp-backlinks-head items-center no-wrap") as head:
                self._icon = ui.icon("fa-solid fa-chevron-down").classes("pp-muted")
                self._title = ui.label("Backlinks").classes("pp-backlinks-title")
            head.on("click", lambda _e: self.toggle())
            self._body = ui.column().classes("pp-backlinks-body")
        self.set_items([])

    def toggle(self) -> None:
        self._open = not self._open
        self._render()

    def set_items(self, items: list[BacklinkItem]) -> None:
        if items == self._items and self._body.default_slot.children:
            return
        self._items = items
        self._render()

    def _render(self) -> None:
        count = len(self._items)
        self._title.set_text(f"Backlinks ({count})" if count else "Backlinks")
        self._icon.props(
            f'name="{"fa-solid fa-chevron-down" if self._open else "fa-solid fa-chevron-right"}"'
        )
        self._body.set_visibility(self._open)
        self._body.clear()
        with self._body:
            if not self._items:
                ui.label("No other note links here.").classes("pp-muted pp-backlinks-empty")
            for item in self._items:
                # one line per note: its title, then the line that links here (the link in bold)
                with ui.row().classes("pp-backlink items-center no-wrap") as row:
                    ui.label(item.title).classes("pp-backlink-title")
                    snippet = item.snippet
                    ui.html(
                        f"{escape(snippet.before)}<b>{escape(snippet.hit)}</b>{escape(snippet.after)}",
                        sanitize=False,
                    ).classes("pp-backlink-snippet")
                row.tooltip(f"{item.path}, line {item.line}")
                row.on("click", lambda _e, i=item: self._on_open(i.path, i.line))
