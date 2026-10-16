"""The tab bar: one chip per open note (name, dirty dot, close button).

Pure presentation. The order, titles and "what is active" come from ``core.tabs.TabList``;
this component renders them and reports clicks, middle-clicks, close buttons and drags
(``static/tabs.js``). A dot marks a note whose text is not safely on disk (unsaved or the
last save failed).
"""

from collections.abc import Callable
from typing import Any

from nicegui import ui

from paper_pile.core.tabs import TabList


class TabBar:
    def __init__(
        self,
        tabs: TabList,
        *,
        on_activate: Callable[[int], None],
        on_close: Callable[[int], None],
        on_move: Callable[[int, int, bool], None],
        on_add_to_chat: Callable[[str], None] = lambda path: None,
    ) -> None:
        self._tabs = tabs
        self._on_activate = on_activate
        self._on_close = on_close
        self._on_move = on_move
        self._on_add_to_chat = on_add_to_chat
        self._bar: ui.element
        self._dots: dict[int, ui.label] = {}

    def build(self) -> None:
        self._bar = ui.row().classes("pp-tabbar no-wrap items-stretch")
        ui.on("pp_tab_move", lambda e: self._moved(e.args))

    def render(self, unsaved: dict[int, bool]) -> None:
        """Rebuild the bar from the tab list (call after open/close/move/rename/activate)."""
        self._bar.clear()
        self._dots.clear()
        titles = self._tabs.titles()
        with self._bar:
            for tab in self._tabs.tabs:
                name, hint = titles[tab.id]
                chip = ui.element("div").classes("pp-tab")
                if tab.id == self._tabs.active:
                    chip.classes("pp-tab-active")
                chip._props["data-doc"] = str(tab.id)
                chip._props["draggable"] = "true"
                chip._props["title"] = tab.path
                chip.on("click", lambda _e, i=tab.id: self._on_activate(i))
                chip.on("mousedown.middle.prevent", lambda _e, i=tab.id: self._on_close(i))
                with chip:
                    ui.label(name).classes("pp-tab-title")
                    if hint is not None:
                        ui.label(hint).classes("pp-tab-hint")
                    dot = ui.label("●").classes("pp-tab-dot")
                    self._dots[tab.id] = dot
                    close = ui.icon("fa-solid fa-xmark").classes("pp-tab-close")
                    close.on("click.stop", lambda _e, i=tab.id: self._on_close(i))
                    with (
                        ui.context_menu(),
                        ui.menu_item(
                            "Add note to chat", lambda _e=None, p=tab.path: self._on_add_to_chat(p)
                        ),
                    ):
                        pass
        self.set_unsaved(unsaved)
        self._bar.client.run_javascript(  # explicit client: we are often outside a page context
            "document.querySelector('.pp-tab-active')"
            "?.scrollIntoView({block: 'nearest', inline: 'nearest'})"
        )

    def set_unsaved(self, unsaved: dict[int, bool]) -> None:
        """Show or hide each tab's dirty dot without rebuilding the bar."""
        for tab_id, dot in self._dots.items():
            if unsaved.get(tab_id, False):
                dot.classes("pp-tab-dirty")
            else:
                dot.classes(remove="pp-tab-dirty")

    def _moved(self, args: dict[str, Any]) -> None:
        self._on_move(int(args["src"]), int(args["dst"]), bool(args["after"]))
