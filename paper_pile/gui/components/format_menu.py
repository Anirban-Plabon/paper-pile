"""The formatting menu (PLAN §4.38): opened by the Ask box's format button or a right-click on a
selection. The user's pinned items first (five by default), then *More* (every item by group)
and *Customize* (which items are pinned). Colour and Link ask for their value in the same box
first; Comment closes the menu and opens the comment window (the one a comment pin opens, with
Add comment; ``comments.js``). ``static/formatmenu.js`` places it and reports clicks outside;
what an item does is :mod:`paper_pile.core.formatting` (the editor pane applies it).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from nicegui import Client, ui

from paper_pile.core.format_items import BY_ID, MAX_PINNED, FormatItem, grouped, toggle_pinned
from paper_pile.core.formatting import COLORS
from paper_pile.gui.icons import line_icon

log = logging.getLogger("paper_pile.format_menu")

TABLE_ITEMS = ("copy", "cut", "paste", "delete")

View = Literal["main", "more", "customize", "color", "link", "table"]


@dataclass(frozen=True, slots=True)
class FormatTarget:
    """What the menu acts on: a tab, the editor side showing it, the selection (UTF-16)."""

    doc_id: int
    slot: int
    start: int
    end: int


class FormatMenu:
    def __init__(
        self,
        *,
        pinned: Callable[[], list[str]],
        save_pinned: Callable[[list[str]], None],
        apply: Callable[[FormatTarget, str, str | None], Awaitable[None]],
        find_notes: Callable[[str], list[str]],
        ai_on: Callable[[], bool],
        add_comment: Callable[[FormatTarget], None],
    ) -> None:
        self._add_comment = add_comment  # the editor's new-comment window for the target
        self._pinned = pinned
        self._save_pinned = save_pinned
        self._apply = apply
        self._find_notes = find_notes  # note names for the link box
        self._ai_on = ai_on
        self._client: Client = ui.context.client
        self._target: FormatTarget | None = None
        self._view: View = "main"
        with ui.teleport("body"):
            self._root = ui.element("div").classes("pp-fmenu")
        self._root.set_visibility(False)
        ui.on("pp_fmenu_close", lambda _e: self.close())

    # ---- opening ----------------------------------------------------------------------------

    def open(self, target: FormatTarget, x: float, y: float, view: View = "main") -> None:
        self._target = target
        self._show(view)
        self._root.set_visibility(True)
        self._client.run_javascript(f"window.ppFmenuPlace && window.ppFmenuPlace({x:.0f}, {y:.0f})")

    def close(self) -> None:
        if self._root.visible:
            self._root.set_visibility(False)
        self._target = None

    @property
    def is_open(self) -> bool:
        return self._root.visible

    # ---- drawing ----------------------------------------------------------------------------

    def _show(self, view: View) -> None:
        self._view = view
        self._root.clear()
        with self._root:
            {
                "main": self._main,
                "more": self._more,
                "customize": self._customize,
                "color": self._color,
                "link": self._link,
                "table": self._table,
            }[view]()
        self._client.run_javascript("window.ppFmenuReplace && window.ppFmenuReplace()")

    def _row(self, item: FormatItem, *, hint: bool = True) -> None:
        with ui.element("div").classes("pp-fmenu-item") as row:
            line_icon(item.icon).classes("pp-fmenu-icon")
            ui.label(item.label).classes("pp-fmenu-label")
            if hint and item.hint:
                ui.label(item.hint).classes("pp-fmenu-hint")
            if item.asks:
                line_icon("chevron-right", "s").classes("pp-fmenu-more")
        row._props["data-id"] = item.id
        row.on("mousedown.prevent", lambda _e, i=item.id: self._pick(i))

    def _link_row(
        self, icon: str, label: str, view: View | None, action: Callable[[], object]
    ) -> None:
        with ui.element("div").classes("pp-fmenu-item pp-fmenu-nav") as row:
            line_icon(icon).classes("pp-fmenu-icon")
            ui.label(label).classes("pp-fmenu-label")
            if view is not None:
                line_icon("chevron-right", "s").classes("pp-fmenu-more")
        row.on("mousedown.prevent", lambda _e: action())

    def _back(self, title: str) -> None:
        with ui.element("div").classes("pp-fmenu-head"):
            back = ui.element("div").classes("pp-fmenu-back")
            with back:
                line_icon("chevron-left", "s")
            back.on("mousedown.prevent", lambda _e: self._show("main"))
            ui.label(title).classes("pp-fmenu-title")

    def _main(self) -> None:
        pinned = [BY_ID[i] for i in self._pinned() if i in BY_ID]
        for item in pinned:
            self._row(item)
        if "copy" not in self._pinned():
            self._row(BY_ID["copy"])  # always at hand (user 2026-11-26), unless pinned already
        ui.element("div").classes("pp-fmenu-sep")
        self._link_row("sliders-horizontal", "More", "more", lambda: self._show("more"))
        self._link_row("pin", "Customize", "customize", lambda: self._show("customize"))
        if self._ai_on():
            ui.element("div").classes("pp-fmenu-sep")
            self._link_row("sparkles", "Ask AI…", None, lambda: self._pick("ask-ai"))

    def _table(self) -> None:
        """A selected block of table cells (or whole rows / columns): the edit items only; the
        table widget does them (tablewidget.js ``blockClipboard``)."""
        for item_id in TABLE_ITEMS:
            self._row(BY_ID[item_id])

    def _more(self) -> None:
        self._back("All items")
        with ui.element("div").classes("pp-fmenu-scroll"):
            for group, items in grouped():
                ui.label(group).classes("pp-fmenu-group")
                for item in items:
                    self._row(item)

    def _customize(self) -> None:
        pinned = self._pinned()
        self._back(f"Pinned items ({len(pinned)}/{MAX_PINNED})")
        with ui.element("div").classes("pp-fmenu-scroll"):
            for group, items in grouped():
                ui.label(group).classes("pp-fmenu-group")
                for item in items:
                    on = item.id in pinned
                    full = not on and len(pinned) >= MAX_PINNED
                    cls = "pp-fmenu-item pp-fmenu-pick" + (" pp-fmenu-on" if on else "")
                    with ui.element("div").classes(cls + (" pp-fmenu-off" if full else "")) as row:
                        line_icon(item.icon).classes("pp-fmenu-icon")
                        ui.label(item.label).classes("pp-fmenu-label")
                        line_icon("check" if on else "pin", "s").classes("pp-fmenu-check")
                    row.on("mousedown.prevent", lambda _e, i=item.id: self._toggle_pin(i))

    def _toggle_pin(self, item_id: str) -> None:
        self._save_pinned(toggle_pinned(self._pinned(), item_id))
        self._show("customize")

    def _color(self) -> None:
        self._back("Text colour")
        with ui.element("div").classes("pp-fmenu-swatches"):
            for name, code in COLORS.items():
                sw = ui.element("div").classes(f"pp-fmenu-swatch pp-fc-{name}")
                sw._props["title"] = name.capitalize()
                sw._props["style"] = f"--sw: {code}"
                sw.on("mousedown.prevent", lambda _e, n=name: self._pick("color", n))
        self._link_row("x", "No colour", None, lambda: self._pick("color", None, force=True))

    def _link(self) -> None:
        self._back("Link")
        box = (
            ui.input(placeholder="Paste a link or type a note name")
            .props("dense borderless autofocus")
            .classes("pp-fmenu-input")
        )
        notes = ui.element("div").classes("pp-fmenu-notes")

        def fill(query: str) -> None:
            notes.clear()
            with notes:
                for name in self._find_notes(query)[:6]:
                    with ui.element("div").classes("pp-fmenu-item") as row:
                        line_icon("file-text").classes("pp-fmenu-icon")
                        ui.label(name).classes("pp-fmenu-label")
                    row.on("mousedown.prevent", lambda _e, n=name: self._pick("link", f"[[{n}]]"))

        def enter() -> Awaitable[None] | None:
            value = (box.value or "").strip()
            if not value:
                return None
            names = self._find_notes(value)
            exact = next((n for n in names if n.lower() == value.lower()), None)
            looks_web = "://" in value or value.startswith(("www.", "mailto:", "#", "/", "./"))
            return self._pick("link", f"[[{exact}]]" if exact and not looks_web else value)

        box.on_value_change(lambda e: fill(str(e.value or "")))
        box.on("keydown.enter", lambda _e: enter())
        fill("")

    # ---- picking ----------------------------------------------------------------------------

    def _pick(
        self, item_id: str, arg: str | None = None, *, force: bool = False
    ) -> Awaitable[None] | None:
        """An item clicked: ask for its value first when it needs one, else run it. Returns the
        run's coroutine, which NiceGUI awaits in the clicked element's slot."""
        item = BY_ID.get(item_id)
        if item_id == "comment" and arg is None:
            target = self._target
            self.close()
            if target is not None:
                self._add_comment(target)
            return None
        if item is not None and item.asks and arg is None and not force:
            self._show(item.asks)  # type: ignore[arg-type]
            return None
        target = self._target
        self.close()
        return self._apply(target, item_id, arg) if target is not None else None
