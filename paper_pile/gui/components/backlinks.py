"""Backlinks under the editor: the notes that link to the open note, with the line of each
link. The toggle sits in the footer bar (left; the status bar fills its right side) and the
list opens above that bar, so the bar's top edge stays level with the profile row's.

While the editor is split, each side has its own toggle and list (the right one starts at the
split divider, like the tab row): the lists open and close together.
It only displays what :mod:`paper_pile.core.index` found."""

from collections.abc import Callable
from dataclasses import dataclass
from html import escape

from nicegui import ui

from paper_pile.core.snippets import Snippet
from paper_pile.gui.icons import line_icon


@dataclass(frozen=True, slots=True)
class BacklinkItem:
    path: str
    title: str
    line: int
    snippet: Snippet


class _Side:
    """One side's toggle (in the footer) and list (above it)."""

    def __init__(self, on_toggle: Callable[[], None]) -> None:
        self.items: list[BacklinkItem] | None = None  # None: never drawn
        with ui.row().classes("pp-backlinks-head items-center no-wrap") as self.head:
            self.icon = line_icon("chevron-right", "s").classes("pp-muted pp-chev")
            self.title = ui.label("Backlinks").classes("pp-backlinks-title")
        self.head.on("click", lambda _e: on_toggle())


class BacklinksPane:
    def __init__(self, on_open: Callable[[str, int, int], None]) -> None:
        self._on_open = on_open  # (path, line, side)
        self._open = False  # closed: the footer line stays level with the profile divider
        self._split = False
        self._sides: list[_Side] = []
        self._bodies: list[ui.column] = []
        self._root: ui.element
        self._lists: ui.row
        self.status_host: ui.element  # the footer's right side (filled by the layout)

    def build(self) -> None:
        self._root = ui.column().classes("pp-backlinks")
        with self._root:
            with ui.row().classes("pp-backlinks-lists no-wrap") as self._lists:
                self._bodies = [ui.column().classes("pp-backlinks-body") for _ in range(2)]
            with ui.row().classes("pp-footer items-center no-wrap"):
                with ui.row().classes("pp-backlinks-side no-wrap items-center"):
                    self._sides.append(_Side(self.toggle))
                with ui.row().classes("pp-backlinks-side no-wrap items-center"):
                    self._sides.append(_Side(self.toggle))
                ui.space()
                self.status_host = ui.element("div").classes("pp-footer-status")
        self._sides[1].head.set_visibility(False)
        self.set_items([])

    def toggle(self) -> None:
        self._open = not self._open
        for side in range(2):
            self._render(side)

    def set_items(self, items: list[BacklinkItem], right: list[BacklinkItem] | None = None) -> None:
        """The left (or only) note's backlinks; ``right``: the split's right note's (``None``:
        not split)."""
        split = right is not None
        if split != self._split:
            self._split = split
            if split:
                self._root.classes("pp-backlinks-split")
            else:
                self._root.classes(remove="pp-backlinks-split")
            self._sides[1].head.set_visibility(split)
            self._bodies[1].set_visibility(split and self._open)
        for side, side_items in enumerate((items, right or [])):
            if side_items != self._sides[side].items:
                self._sides[side].items = side_items
                self._render(side)

    def _render(self, index: int) -> None:
        side, body = self._sides[index], self._bodies[index]
        items = side.items or []
        count = len(items)
        side.title.set_text(f"Backlinks ({count})" if count else "Backlinks")
        side.icon.classes(
            add="pp-open" if self._open else "", remove="" if self._open else "pp-open"
        )
        body.set_visibility(self._open and (index == 0 or self._split))
        self._lists.set_visibility(self._open)
        body.clear()
        with body:
            if not items:
                ui.label("No other note links here.").classes("pp-muted pp-backlinks-empty")
            for item in items:
                # one line per note: its title, then the line that links here (the link in bold)
                with ui.row().classes("pp-backlink items-center no-wrap") as row:
                    ui.label(item.title).classes("pp-backlink-title")
                    snippet = item.snippet
                    ui.html(
                        f"{escape(snippet.before)}<b>{escape(snippet.hit)}</b>{escape(snippet.after)}",
                        sanitize=False,
                    ).classes("pp-backlink-snippet")
                row.on("click", lambda _e, i=item: self._on_open(i.path, i.line, index))
