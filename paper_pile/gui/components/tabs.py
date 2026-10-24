"""The tab bar: one chip per open note (name, dirty dot, close button).

Pure presentation. The order, titles and "what is active" come from ``core.tabs.TabList``;
this component renders them and reports clicks, middle-clicks, close buttons and drags
(``static/tabs.js``). A dot marks a note whose text is not safely on disk (unsaved or the
last save failed).

In split view the tab of the note on the right side sits in a second group that starts at the
split divider (``static/split.js`` keeps ``--pp-split-left`` on the editor column); each side's
note is marked, the side being typed in more strongly.

Many tabs: they shrink (down to a minimum width, names cut short) before they overflow; then
the row scrolls (mouse wheel, or the ‹ › arrows ``static/tabs.js`` shows at a cut-off edge) and
the list button before the note buttons lists every open tab. Pinned tabs come first, with a
pin and no ×. A + after the tabs makes a new
note in the vault's top folder.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nicegui import background_tasks, ui

from paper_pile.core.tabs import TabList
from paper_pile.gui.icons import icon_button, line_icon
from paper_pile.gui.tips import tip


@dataclass(frozen=True, slots=True)
class SplitTabs:
    """What each side of a split shows (tab ids) and which side is being typed in."""

    left: int | None
    right: int | None
    active_slot: int


# a tab menu entry: (icon, label, action — may return an awaitable); None draws a divider
TabMenuItem = tuple[str, str, Callable[[], Any]] | None


def _run(action: Callable[[], Any]) -> None:
    result = action()
    if inspect.isawaitable(result):
        background_tasks.create(result)  # type: ignore[arg-type]


class TabBar:
    def __init__(
        self,
        tabs: TabList,
        *,
        on_activate: Callable[[int], None],
        on_close: Callable[[int], None],
        on_move: Callable[[int, int, bool], None],
        menu: Callable[[int, str], list[TabMenuItem]] = lambda tab_id, path: [],
        on_toggle_pane: Callable[[str], None] = lambda pane: None,
        on_activate_side: Callable[[int, int], None] | None = None,
        on_new: Callable[[], None] = lambda: None,
    ) -> None:
        self._tabs = tabs
        self._on_activate = on_activate
        self._on_close = on_close
        self._on_move = on_move
        self._menu = menu  # the items of a tab's right-click menu (None: a divider)
        self._on_toggle_pane = on_toggle_pane
        self._on_activate_side = on_activate_side  # (tab id, side) while split
        self._on_new = on_new  # the + after the tabs: a new note in the vault's top folder
        self._strip: ui.row
        self._right: ui.element
        self.toggles: dict[str, ui.button] = {}
        self._bar: ui.element
        self._dots: dict[int, ui.label] = {}
        self._list_menu: ui.menu
        self._list_count: ui.label

    def build(self) -> None:
        with ui.row().classes("pp-tabstrip pp-dragzone no-wrap items-center") as self._strip:
            self._bar = ui.row().classes("pp-tabbar pp-dragzone no-wrap items-stretch")
            self._right = ui.row().classes("pp-tabbar pp-tabbar-right pp-dragzone no-wrap")
            self._right.classes("items-stretch")
            self._right.set_visibility(False)
            icon_button("plus", self._on_new, "New note", size="m").classes("pp-tab-new")
            with (
                ui.button(color=None)
                .props("flat dense no-caps")
                .classes("pp-icon-btn pp-tabs-list") as list_button
            ):
                line_icon("chevrons-down")
                self._list_count = ui.label("").classes("pp-tabs-list-count")
                self._list_menu = ui.menu().classes("pp-note-menu pp-tabs-list-menu")
                self._list_menu.props("anchor='bottom right' self='top right'")
            tip(list_button, "All open tabs")
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
        self._fill_list(split)
        self.set_unsaved(unsaved)
        self._bar.client.run_javascript(  # explicit client: we are often outside a page context
            "document.querySelector('.pp-tab-active')"
            "?.scrollIntoView({block: 'nearest', inline: 'nearest'})"
        )

    def _chip(self, tab_id: int, path: str, side: int, split: SplitTabs | None) -> None:
        name, hint = self._tabs.titles()[tab_id]
        entry = self._tabs.get(tab_id)
        pinned = entry is not None and entry.pinned
        chip = ui.element("div").classes("pp-tab" + (" pp-tab-pinned" if pinned else ""))
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
        if not pinned:  # a pinned tab never closes by a stray middle-click
            chip.on("mousedown.middle.prevent", lambda _e, i=tab_id: self._on_close(i))
        with chip:
            if pinned:
                line_icon("pin", "s").classes("pp-tab-pin")
            ui.label(name).classes("pp-tab-title")
            if hint is not None:
                ui.label(hint).classes("pp-tab-hint")
            dot = ui.label("●").classes("pp-tab-dot")
            self._dots.setdefault(tab_id, dot)
            if not pinned:  # closed from its menu (or Ctrl+W) instead
                close = line_icon("x", "s").classes("pp-tab-close")
                close.on("click.stop", lambda _e, i=tab_id: self._on_close(i))
            items = self._menu(tab_id, path)
            if items:
                with ui.context_menu().classes("pp-note-menu"):
                    for item in items:
                        if item is None:
                            ui.separator()
                            continue
                        icon, label, action = item
                        with ui.menu_item(on_click=lambda _e=None, a=action: _run(a)).classes(
                            "pp-note-menu-item"
                        ):
                            line_icon(icon).classes("pp-note-menu-icon")
                            ui.label(label).classes("pp-note-menu-label")

    def _fill_list(self, split: SplitTabs | None) -> None:
        """The list button's menu: every open tab, the one(s) on screen marked."""
        tabs = self._tabs.tabs
        titles = self._tabs.titles()
        shown = {self._tabs.active} if split is None else {split.left, split.right}
        self._list_count.set_text(str(len(tabs)))
        self._list_menu.clear()
        with self._list_menu:
            for tab in tabs:
                name, hint = titles[tab.id]
                item = ui.menu_item(on_click=lambda _e=None, i=tab.id: self._on_activate(i))
                item.classes("pp-note-menu-item")
                if tab.id in shown:
                    item.classes("pp-tabs-list-on")
                with item:
                    line_icon("file-text").classes("pp-note-menu-icon")
                    ui.label(name).classes("pp-note-menu-label")
                    if hint is not None:
                        ui.label(hint).classes("pp-tab-hint")

    def set_unsaved(self, unsaved: dict[int, bool]) -> None:
        """Show or hide each tab's dirty dot without rebuilding the bar."""
        for tab_id, dot in self._dots.items():
            if unsaved.get(tab_id, False):
                dot.classes("pp-tab-dirty")
            else:
                dot.classes(remove="pp-tab-dirty")

    def _moved(self, args: dict[str, Any]) -> None:
        self._on_move(int(args["src"]), int(args["dst"]), bool(args["after"]))
