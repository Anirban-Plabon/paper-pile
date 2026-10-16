"""The right pane: a tab strip (AI chat, and Settings while it is open) over the active view.

Settings is a tab, not a dialog: it opens here, can be closed with its cross like an editor tab,
and keeps the chat (and its attachments) alive underneath. Icons are Font Awesome (vendored).
"""

from collections.abc import Callable

from nicegui import ui

CHAT_ICON = "fa-regular fa-comments"
SETTINGS_ICON = "fa-solid fa-gear"  # Font Awesome Free has no outline gear
CLOSE_ICON = "fa-regular fa-circle-xmark"


class RightPane:
    def __init__(
        self,
        on_open_settings: Callable[[ui.column], None],
        on_wide: Callable[[bool], None] = lambda wide: None,
    ) -> None:
        self._open_settings_into = on_open_settings
        self._on_wide = on_wide
        self._settings_open = False
        self._active = "chat"
        self._bar: ui.row
        self.chat_host: ui.column
        self.settings_host: ui.column

    def build(self) -> None:
        """Create the strip and the two hosts; the caller fills ``chat_host`` right after."""
        with ui.column().classes("pp-pane pp-right"):
            self._bar = ui.row().classes("pp-rtabbar pp-right-tabs no-wrap items-stretch")
            self.chat_host = ui.column().classes("pp-right-body pp-grow")
            self.settings_host = ui.column().classes("pp-right-body pp-grow")
        self._render()

    # ---- state ---------------------------------------------------------------------------

    @property
    def settings_open(self) -> bool:
        return self._settings_open

    def show(self, name: str) -> None:
        self._active = name if name == "chat" or self._settings_open else "chat"
        self._render()

    def open_settings(self) -> None:
        """Open (or rebuild) the Settings tab and show it."""
        self._settings_open = True
        self._active = "settings"
        self.settings_host.clear()
        self._open_settings_into(self.settings_host)
        self._render()

    def close_settings(self) -> None:
        self._settings_open = False
        self._active = "chat"
        self.settings_host.clear()
        self._render()

    # ---- drawing -------------------------------------------------------------------------

    def _render(self) -> None:
        self._on_wide(self._active == "settings")  # Settings gets a wide pane
        self.chat_host.set_visibility(self._active == "chat")
        self.settings_host.set_visibility(self._active == "settings")
        self._bar.clear()
        with self._bar:
            self._tab("chat", "AI chat", CHAT_ICON, closable=False)
            if self._settings_open:
                self._tab("settings", "Settings", SETTINGS_ICON, closable=True)

    def _tab(self, name: str, title: str, icon: str, *, closable: bool) -> None:
        chip = ui.element("div").classes("pp-rtab")
        if name == self._active:
            chip.classes("pp-rtab-active")
        chip.on("click", lambda _e, n=name: self.show(n))
        with chip:
            ui.icon(icon).classes("pp-rtab-icon")
            ui.label(title).classes("pp-rtab-title")
            if closable:
                close = ui.icon(CLOSE_ICON).classes("pp-rtab-close")
                close.on("click.stop", lambda _e: self.close_settings())
                close.tooltip("Close")
