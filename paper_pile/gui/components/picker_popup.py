"""A search-and-pick popup near the top of the window, shared by the quick switcher (Ctrl+O)
and the command palette (Ctrl+P) (PLAN §4.18).

The caller supplies ``search(query) -> items``; the popup lists them, ↑/↓ move the mark, Enter
picks (Ctrl+Enter picks "aside", e.g. into the split), Esc or a click outside closes. Matching
and ordering are the caller's (``core.picker`` / ``core.commands.match_score``).
"""

from collections.abc import Callable
from dataclasses import dataclass

from nicegui import ui

from paper_pile.gui.dialog import Dialog
from paper_pile.gui.icons import close_button, line_icon


@dataclass(frozen=True, slots=True)
class PickItem:
    key: str
    title: str
    subtitle: str = ""  # muted, after the title (a note's folder)
    hint: str = ""  # right-aligned (a shortcut)
    icon: str = ""
    group: str = ""  # a heading drawn above the first item of each group (the palette)


Picked = tuple[PickItem, bool]  # (item, aside)
# no open / close animation: the popup is there at once (Ctrl+P, Ctrl+O)
NO_ANIMATION = "position=top transition-show=none transition-hide=none transition-duration=0"


class PickerPopup:
    def __init__(self, host: ui.element) -> None:
        self._host = host  # dialogs are created inside it
        self._dialog: ui.dialog | None = None

    async def pick(
        self, placeholder: str, search: Callable[[str], list[PickItem]]
    ) -> Picked | None:
        """Show the popup until something is picked (or it is closed: ``None``)."""
        if self._dialog is not None:  # Ctrl+O while the palette is open: replace it
            self._dialog.submit(None)
        items: list[PickItem] = []
        rows: list[ui.element] = []
        mark = 0

        with (
            self._host,
            # no open / close animation: it is there at once (Ctrl+P, Ctrl+O)
            Dialog().props(
                "position=top transition-show=none transition-hide=none transition-duration=0"
            ) as dialog,
            ui.card().classes("pp-picker"),
        ):
            with ui.row().classes("pp-picker-head items-center no-wrap"):
                field = (
                    ui.input(placeholder=placeholder)
                    .props("dense borderless autofocus")
                    .classes("pp-picker-input")
                )
                close_button(lambda: dialog.submit(None), "Close (Esc)").classes("pp-picker-close")
            listing = ui.column().classes("pp-picker-list")
        self._dialog = dialog

        def show_mark(new: int) -> None:
            nonlocal mark
            if not rows:
                return
            rows[mark].classes(remove="pp-picker-on")
            mark = max(0, min(len(rows) - 1, new))
            rows[mark].classes("pp-picker-on")
            rows[mark].run_method("scrollIntoView", {"block": "nearest"})

        def fill(query: str) -> None:
            nonlocal items, mark
            items = search(query)
            rows.clear()
            mark = 0
            listing.clear()
            with listing:
                if not items:
                    ui.label("Nothing found").classes("pp-muted pp-picker-none")
                group = ""
                for i, item in enumerate(items):
                    if item.group and item.group != group:
                        group = item.group
                        ui.label(group).classes("pp-picker-group")
                    row = ui.row().classes("pp-picker-row items-center no-wrap")
                    with row:
                        if item.icon:
                            line_icon(item.icon).classes("pp-picker-icon")
                        ui.label(item.title).classes("pp-picker-title")
                        if item.subtitle:
                            ui.label(item.subtitle).classes("pp-picker-sub")
                        ui.space()
                        if item.hint:  # a shortcut: each key in its own rounded box
                            with ui.row().classes("pp-picker-keys items-center no-wrap"):
                                for part in item.hint.split("+"):
                                    ui.label(part).classes("pp-kbd")
                    row.on("click", lambda _e, i=i: choose(i, aside=False))
                    rows.append(row)
            if rows:
                rows[0].classes("pp-picker-on")

        def choose(i: int, *, aside: bool) -> None:
            if 0 <= i < len(items):
                dialog.submit((items[i], aside))

        field.on_value_change(lambda e: fill(e.value or ""))
        field.on("keydown.down.prevent", lambda: show_mark(mark + 1))
        field.on("keydown.up.prevent", lambda: show_mark(mark - 1))
        field.on("keydown.enter.exact.prevent", lambda: choose(mark, aside=False))
        field.on("keydown.ctrl.enter.prevent", lambda: choose(mark, aside=True))
        fill("")
        result = await dialog
        if self._dialog is dialog:
            self._dialog = None
        dialog.delete()
        return result  # type: ignore[no-any-return]
