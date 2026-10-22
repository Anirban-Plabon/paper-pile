"""The Outline tab of the right pane (PLAN §4.18): the headings of the note on screen.

Indented by level; a click puts the caret on that heading; the section holding the caret is
marked. Headings come from ``core.parser.headings`` (none from inside code blocks). The list is
only rebuilt when the headings change, so following the caret is cheap.
"""

from collections.abc import Callable

from nicegui import ui

from paper_pile.core.parser import Heading, headings, section_at

INDENT_PX = 12


class OutlinePane:
    def __init__(self, on_jump: Callable[[int], None]) -> None:
        self._on_jump = on_jump  # 1-based line
        self._text: str | None = None
        self._heads: list[Heading] = []
        self._rows: list[ui.element] = []
        self._marked: int | None = None
        self._list: ui.column

    def build(self) -> None:
        self._list = ui.column().classes("pp-outline")
        self._draw()

    def show(self, text: str | None, line: int) -> None:
        """The note on screen (``None``: no note) and the caret's 1-based line."""
        if text != self._text:
            self._text = text
            heads = headings(text) if text is not None else []
            if heads != self._heads or not self._rows:
                self._heads = heads
                self._draw()
        self._mark(section_at(self._heads, line) if self._heads else None)

    def _draw(self) -> None:
        self._list.clear()
        self._rows = []
        self._marked = None
        with self._list:
            if not self._heads:
                note = "No headings in this note." if self._text is not None else "No note open."
                ui.label(note).classes("pp-muted pp-outline-none")
                return
            top = min(h.level for h in self._heads)
            for head in self._heads:
                row = ui.label(head.text or "(empty heading)").classes(
                    f"pp-outline-row pp-outline-h{head.level}"
                )
                row.style(f"padding-left: {10 + (head.level - top) * INDENT_PX}px")
                row.on("click", lambda _e, line=head.line: self._on_jump(line))
                self._rows.append(row)

    def _mark(self, index: int | None) -> None:
        if index == self._marked:
            return
        if self._marked is not None and self._marked < len(self._rows):
            self._rows[self._marked].classes(remove="pp-outline-on")
        self._marked = index
        if index is not None and index < len(self._rows):
            self._rows[index].classes("pp-outline-on")
