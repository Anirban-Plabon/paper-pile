"""The tab bar: one chip per open note (name, dirty dot, close button).

Pure presentation. The order, titles and "what is active" come from ``core.tabs.TabList``;
this component renders them and reports clicks, middle-clicks, close buttons and drags
(``static/tabs.js``). A dot marks a note whose text is not safely on disk (unsaved or the
last save failed).

In split view the tab of the note on the right side sits in a second group that starts at the
split divider (``static/split.js`` keeps ``--pp-split-left`` on the editor column); each side's
note is marked, the side being typed in more strongly.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nicegui import ui

from paper_pile.core.tabs import TabList
from paper_pile.gui.icons import icon_button, line_icon


@dataclass(frozen=True, slots=True)
class SplitTabs:
    """What each side of a split shows (tab ids) and which side is being typed in."""

    left: int | None
    right: int | None
    active_slot: int


class TabBar:
    def __init__(
        self,
        tabs: TabList,
        *,
        on_activate: Callable[[int], None],
        on_close: Callable[[int], None],
        on_move: Callable[[int, int, bool], None],
        on_add_to_chat: Callable[[str], None] = lambda path: None,
        on_toggle_pane: Callable[[str], None] = lambda pane: None,
        on_activate_side: Callable[[int, int], None] | None = None,
    ) -> None:
        self._tabs = tabs
        self._on_activate = on_activate
        self._on_close = on_close
        self._on_move = on_move
        self._on_add_to_chat = on_add_to_chat
        self._on_toggle_pane = on_toggle_pane
        self._on_activate_side = on_activate_side  # (tab id, side) while split
        self._strip: ui.row
        self._right: ui.element
        self.toggles: dict[str, ui.button] = {}
        self.menu_host: ui.element
        self._bar: ui.element
        self._dots: dict[int, ui.label] = {}

    def build(self) -> None:
        with ui.row().classes("pp-tabstrip pp-dragzone no-wrap items-center") as self._strip:
            self._bar = ui.row().classes("pp-tabbar pp-dragzone no-wrap items-stretch")
            self._right = ui.row().classes("pp-tabbar pp-tabbar-right pp-dragzone no-wrap")
            self._right.classes("items-stretch")
            self._right.set_visibility(False)
            self.menu_host = ui.element("div").classes("pp-tab-more")  # the ⋯ note menu
            self.toggles["right"] = icon_button(
                "panel-right-close", lambda: self._on_toggle_pane("right"), "Hide AI chat (Ctrl+L)"
            )
        ui.on("pp_tab_move", lambda e: self._moved(e.args))

    def render(self, unsaved: dict[int, bool], split: SplitTabs | None = None) -> None:
        """Rebuild the bar from the tab list (call after open/close/move/rename/activate)."""
        self._bar.clear()
        self._right.clear()
        self._dots.clear()
        self._right.set_visibility(split is not None and split.right is not None)
        if split is not None:
            self._strip.classes("pp-tabstrip-split")
        else:
            self._strip.classes(remove="pp-tabstrip-split")
        right = split.right if split is not None else None
        with self._bar:
            for tab in self._tabs.tabs:
                if tab.id != right or (split is not None and split.left == right):
                    self._chip(tab.id, tab.path, 0, split)
        if right is not None:
            path = next(t.path for t in self._tabs.tabs if t.id == right)
            with self._right:
                self._chip(right, path, 1, split)
        self.set_unsaved(unsaved)
        self._bar.client.run_javascript(  # explicit client: we are often outside a page context
            "document.querySelector('.pp-tab-active')"
            "?.scrollIntoView({block: 'nearest', inline: 'nearest'})"
        )

    def _chip(self, tab_id: int, path: str, side: int, split: SplitTabs | None) -> None:
        name, hint = self._tabs.titles()[tab_id]
        chip = ui.element("div").classes("pp-tab")
        if split is None:
            if tab_id == self._tabs.active:
                chip.classes("pp-tab-active")
        elif tab_id == (split.left, split.right)[side]:
            chip.classes("pp-tab-active" if side == split.active_slot else "pp-tab-shown")
        chip._props["data-doc"] = str(tab_id)
        chip._props["draggable"] = "true"
        if split is not None and self._on_activate_side is not None:
            chip.on("click", lambda _e, i=tab_id, s=side: self._on_activate_side(i, s))  # type: ignore[misc]
        else:
            chip.on("click", lambda _e, i=tab_id: self._on_activate(i))
        chip.on("mousedown.middle.prevent", lambda _e, i=tab_id: self._on_close(i))
        with chip:
            ui.label(name).classes("pp-tab-title")
            if hint is not None:
                ui.label(hint).classes("pp-tab-hint")
            dot = ui.label("●").classes("pp-tab-dot")
            self._dots.setdefault(tab_id, dot)
            close = line_icon("x", "s").classes("pp-tab-close")
            close.on("click.stop", lambda _e, i=tab_id: self._on_close(i))
            with (
                ui.context_menu(),
                ui.menu_item("Add note to chat", lambda _e=None, p=path: self._on_add_to_chat(p)),
            ):
                pass

    def set_unsaved(self, unsaved: dict[int, bool]) -> None:
        """Show or hide each tab's dirty dot without rebuilding the bar."""
        for tab_id, dot in self._dots.items():
            if unsaved.get(tab_id, False):
                dot.classes("pp-tab-dirty")
            else:
                dot.classes(remove="pp-tab-dirty")

    def _moved(self, args: dict[str, Any]) -> None:
        self._on_move(int(args["src"]), int(args["dst"]), bool(args["after"]))
