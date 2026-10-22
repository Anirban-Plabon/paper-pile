"""The right pane: a tab strip (AI chat, Calendar, and Settings / a ``#tag`` list while they
are open) over the active view. AI chat and Calendar are listed only while their feature is on
(``features``); with neither on and nothing else open the pane has nothing to show.

Settings is a tab, not a dialog: it opens here, can be closed with its cross like an editor tab,
and keeps the chat (and its attachments) alive underneath. Icons are Font Awesome (vendored).
"""

from collections.abc import Callable

from nicegui import ui

from paper_pile.gui.icons import line_icon

CHAT_ICON = "messages-square"
CALENDAR_ICON = "calendar"
SETTINGS_ICON = "settings"  # a line icon (gui/icons.py); Font Awesome Free has no outline gear
TAG_ICON = "hash"
CLOSE_ICON = "x"


class RightPane:
    def __init__(
        self,
        on_open_settings: Callable[[ui.column, str | None], None],
        on_wide: Callable[[bool], None] = lambda wide: None,
        on_show_calendar: Callable[[], None] = lambda: None,
        features: Callable[[], set[str]] = lambda: {"chat", "calendar"},
        on_empty: Callable[[], None] = lambda: None,
    ) -> None:
        self._features = features
        self._on_empty = on_empty  # the last tab went away: the pane has nothing to show
        self._open_settings_into = on_open_settings
        self._on_wide = on_wide
        self._on_show_calendar = on_show_calendar
        self._settings_open = False
        self._tag = ""  # the open #tag tab ("" = none)
        self._active = "chat"
        self._bar: ui.row
        self.chat_host: ui.column
        self.calendar_host: ui.column
        self.settings_host: ui.column
        self.tag_host: ui.column

    def build(self) -> None:
        """Create the strip and the hosts; the caller fills ``chat_host`` and ``calendar_host``."""
        with ui.column().classes("pp-pane pp-right"):
            self._bar = ui.row().classes(
                "pp-rtabbar pp-right-tabs pp-dragzone no-wrap items-stretch"
            )
            self.chat_host = ui.column().classes("pp-right-body pp-grow")
            self.calendar_host = ui.column().classes("pp-right-body pp-grow")
            self.settings_host = ui.column().classes("pp-right-body pp-grow")
            self.tag_host = ui.column().classes("pp-right-body pp-grow")
        self._render()

    # ---- state ---------------------------------------------------------------------------

    @property
    def settings_open(self) -> bool:
        return self._settings_open

    def tabs(self) -> list[str]:
        """The tabs on the strip now, left to right."""
        names = [n for n in ("chat", "calendar") if n in self._features()]
        if self._settings_open:
            names.append("settings")
        if self._tag:
            names.append("tag")
        return names

    def has_tabs(self) -> bool:
        return bool(self.tabs())

    def show(self, name: str) -> None:
        self._active = name
        self._render()
        if self._active == "calendar":
            self._on_show_calendar()

    def open_settings(self, page: str | None = None) -> None:
        """Open (or rebuild) the Settings tab, on ``page`` (a section name) if given."""
        self._settings_open = True
        self._active = "settings"
        self.settings_host.clear()
        self._open_settings_into(self.settings_host, page)
        self._render()

    def close_settings(self) -> None:
        self._settings_open = False
        self._active = "chat"
        self.settings_host.clear()
        self._render()

    def open_tag(self, tag: str) -> None:
        """Show the ``#tag`` tab (one at a time: a new tag replaces the shown one)."""
        self._tag = tag
        self._active = "tag"
        self._render()

    def close_tag(self) -> None:
        self._tag = ""
        if self._active == "tag":
            self._active = "chat"
        self._render()

    # ---- drawing -------------------------------------------------------------------------

    def refresh(self) -> None:
        """A feature was switched on or off: redraw the strip."""
        self._render()

    def _render(self) -> None:
        tabs = self.tabs()
        if self._active not in tabs:  # closed, or its feature switched off
            self._active = tabs[0] if tabs else ""
        self._on_wide(self._active == "settings")  # Settings gets a wide pane
        self.chat_host.set_visibility(self._active == "chat")
        self.calendar_host.set_visibility(self._active == "calendar")
        self.settings_host.set_visibility(self._active == "settings")
        self.tag_host.set_visibility(self._active == "tag")
        self._bar.clear()
        if not tabs:
            self._on_empty()
        with self._bar:
            for name in tabs:
                if name == "chat":
                    self._tab("chat", "AI chat", CHAT_ICON, closable=False)
                elif name == "calendar":
                    self._tab("calendar", "Calendar", CALENDAR_ICON, closable=False)
                elif name == "settings":
                    self._tab("settings", "Settings", SETTINGS_ICON, closable=True)
                else:
                    self._tab("tag", self._tag, TAG_ICON, closable=True)

    def _tab(self, name: str, title: str, icon: str, *, closable: bool) -> None:
        chip = ui.element("div").classes("pp-rtab")
        if name == self._active:
            chip.classes("pp-rtab-active")
        chip.on("click", lambda _e, n=name: self.show(n))
        chip._props["data-name"] = title  # shown as a hover title only in icon-only mode (tabs.js)
        with chip:
            line_icon(icon).classes("pp-rtab-icon")
            ui.label(title).classes("pp-rtab-title")
            if closable:
                close = line_icon(CLOSE_ICON, "s").classes("pp-rtab-close")
                close.on(
                    "click.stop",
                    lambda _e, n=name: self.close_tag() if n == "tag" else self.close_settings(),
                )
