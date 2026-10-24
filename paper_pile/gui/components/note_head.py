"""The bar on top of each editor (P21): ‹ › jump to the previous / next ``#`` / ``##`` section,
then the note's title and the section at the top of the view (each cut short with … when long),
then the note's own buttons (split, AI, ⋯) on the right. In split view each side has its own
bar; the side being typed in is marked, and a click on its title shows another note there.

Pure presentation: the editor pane fills the right-hand buttons (``tools``) and decides what the
title, the section and the arrows are (``core/sections.py``).
"""

from collections.abc import Callable

from nicegui import ui

from paper_pile.gui.icons import icon_button
from paper_pile.gui.tips import tip


class NoteHead:
    def __init__(
        self,
        *,
        on_prev: Callable[[], None],
        on_next: Callable[[], None],
        on_title: Callable[[], None],
    ) -> None:
        self._on_prev = on_prev
        self._on_next = on_next
        self._on_title = on_title  # split view: show another note on this side
        self.bar: ui.row
        self.tools: ui.element  # the note's buttons (filled by the editor pane)
        self._prev: ui.button
        self._next: ui.button
        self._title: ui.label
        self._section: ui.label
        self._sep: ui.label
        self._shown: tuple[str, str, bool, bool] | None = None
        self._split = False

    def build(self) -> None:
        with ui.row().classes("pp-notehead items-center no-wrap") as self.bar:
            with ui.row().classes("pp-notehead-nav items-center no-wrap"):
                self._prev = icon_button("chevron-up", self._on_prev, "Previous section", "m")
                self._next = icon_button("chevron-down", self._on_next, "Next section", "m")
            with ui.row().classes("pp-notehead-crumb items-center no-wrap"):
                self._title = ui.label("").classes("pp-notehead-title")
                self._title.on("click", lambda _e: self._on_title())
                self._sep = ui.label("›").classes("pp-notehead-sep")
                self._section = ui.label("").classes("pp-notehead-section")
            self.tools = ui.element("div").classes("pp-seg pp-tools pp-tools-row pp-notehead-tools")

    def show(self, title: str, section: str, can_prev: bool, can_next: bool) -> None:
        """Name the note and the section on screen; an arrow with nowhere to go is dimmed."""
        shown = (title, section, can_prev, can_next)
        if shown == self._shown:
            return
        self._shown = shown
        self._title.set_text(title)
        self._section.set_text(section)
        self._sep.set_visibility(bool(section))
        self._section.set_visibility(bool(section))
        tip(self._section, section)  # the whole name, when it is cut short
        self._title_tip()
        for button, on in ((self._prev, can_prev), (self._next, can_next)):
            if on:
                button.props(remove="disable")
            else:
                button.props("disable")

    def _title_tip(self) -> None:
        title = self._shown[0] if self._shown else ""
        tip(self._title, f"{title} · show another note here" if self._split else title)

    def set_split(self, split: bool, active: bool) -> None:
        """In split view the title picks another note, and the side being typed in is marked."""
        if split != self._split:
            self._split = split
            if split:
                self.bar.classes("pp-notehead-split")
            else:
                self.bar.classes(remove="pp-notehead-split")
            self._title_tip()
        if split and active:
            self.bar.classes("pp-notehead-active")
        else:
            self.bar.classes(remove="pp-notehead-active")
