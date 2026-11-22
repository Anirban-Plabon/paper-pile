"""The bar on top of each editor (P21): ‹ › jump to the previous / next ``#`` – ``###`` section,
then the note's title and the trail of headings above the view (``title › H1 › H2 › H3``, each at
most 3 words then …; in split view the middle ones 1 word; a click on a heading jumps to it — user
2026-11-22),
then the note's own buttons on the right: ⋯, and in split view × (close this side) before it —
boxed together only while there are two (user, 2026-11-04). In split view each side has its own
bar; the side being typed in is marked, and a click on its title shows another note there.

Pure presentation: the editor pane fills the right-hand buttons (``tools``) and decides what the
title, the section and the arrows are (``core/sections.py``).
"""

from collections.abc import Callable

from nicegui import ui

from paper_pile.core.parser import Heading
from paper_pile.core.sections import short_label
from paper_pile.gui.icons import icon_button
from paper_pile.gui.tips import tip


class NoteHead:
    def __init__(
        self,
        *,
        on_prev: Callable[[], None],
        on_next: Callable[[], None],
        on_title: Callable[[], None],
        on_close: Callable[[], None],
        on_heading: Callable[[int], None],
    ) -> None:
        self._on_heading = on_heading  # a trail part clicked: jump to that heading's line
        self._on_close = on_close  # split view: close this side
        self._on_prev = on_prev
        self._on_next = on_next
        self._on_title = on_title  # split view: show another note on this side
        self.bar: ui.row
        self.tools: ui.element  # the note's buttons (filled by the editor pane)
        self._prev: ui.button
        self._next: ui.button
        self._title: ui.label
        self._trail: ui.element
        self._close: ui.button
        self._shown: tuple[str, tuple[Heading, ...], bool, bool, bool] | None = None
        self._split = False

    def build(self) -> None:
        with ui.row().classes("pp-notehead items-center no-wrap") as self.bar:
            with ui.row().classes("pp-notehead-nav items-center no-wrap"):
                self._prev = icon_button("chevron-up", self._on_prev, "Previous section", "m")
                self._next = icon_button("chevron-down", self._on_next, "Next section", "m")
            with ui.row().classes("pp-notehead-crumb items-center no-wrap"):
                self._title = ui.label("").classes("pp-notehead-title")
                self._title.on("click", lambda _e: self._on_title())
                self._trail = ui.element("div").classes("pp-notehead-trail")
            self.tools = ui.element("div").classes("pp-tools-row pp-notehead-tools")
            with self.tools:
                self._close = icon_button("x", self._on_close, "Close this side", "m")
                self._close.set_visibility(False)

    def show(self, title: str, trail: list[Heading], can_prev: bool, can_next: bool) -> None:
        """Name the note and the headings above the view; an arrow with nowhere to go is dimmed."""
        shown = (title, tuple(trail), can_prev, can_next, self._split)
        if shown == self._shown:
            return
        self._shown = shown
        self._title.set_text(short_label(title))
        self._title_tip()
        self._draw_trail(trail)
        for button, on in ((self._prev, can_prev), (self._next, can_next)):
            if on:
                button.props(remove="disable")
            else:
                button.props("disable")

    def _draw_trail(self, trail: list[Heading]) -> None:
        self._trail.clear()
        last = len(trail) - 1
        with self._trail:
            for i, head in enumerate(trail):
                ui.label("›").classes("pp-notehead-sep")
                middle = self._split and 0 < i < last  # split view: the middle ones 1 word
                part = ui.label(short_label(head.text, 1) if middle else short_label(head.text))
                part.classes("pp-notehead-part" + (" pp-notehead-last" if i == last else ""))
                part.on("click", lambda _e, line=head.line: self._on_heading(line))
                tip(part, head.text)

    def _title_tip(self) -> None:
        title = self._shown[0] if self._shown else ""  # the whole name (the bar may cut it)
        tip(self._title, f"{title} · show another note here" if self._split else title)

    def set_split(self, split: bool, active: bool) -> None:
        """In split view the title picks another note, and the side being typed in is marked."""
        if split != self._split:
            self._split = split
            boxed = "pp-seg pp-tools"  # × and ⋯ in one box; ⋯ alone needs none
            if split:
                self.bar.classes("pp-notehead-split")
                self.tools.classes(boxed)
            else:
                self.bar.classes(remove="pp-notehead-split")
                self.tools.classes(remove=boxed)
            self._close.set_visibility(split)
            self._title_tip()
        if split and active:
            self.bar.classes("pp-notehead-active")
        else:
            self.bar.classes(remove="pp-notehead-active")
