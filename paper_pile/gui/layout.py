"""The 3-pane frame: [file tree | tabs + editor | AI chat] over a status bar.

Pane widths (px) and open/closed state are remembered per vault in ``session.json``.
A pane keeps its last width while collapsed, so re-opening restores it.
"""

import asyncio
import logging
from pathlib import Path

from nicegui import ui

from paper_pile.core.session import SessionState, load_session, save_session
from paper_pile.gui.components.chat import chat_panel
from paper_pile.gui.components.statusbar import StatusBar, status_bar

log = logging.getLogger("paper_pile.layout")

# (min, max) pane width in px while open. Dragging stops at the limits.
WIDTH_LIMITS = {"left": (180, 480), "right": (280, 640)}
SAVE_DELAY_S = 0.4


class PaneSplitter(ui.splitter):
    """A px-sized splitter whose limits can change (collapsed panes are pinned to 0)."""

    def set_limits(self, low: int, high: int) -> None:
        self._props["limits"] = [low, high]
        self.update()


def clamp_width(pane: str, width: int) -> int:
    low, high = WIDTH_LIMITS[pane]
    return max(low, min(high, width))


class MainLayout:
    def __init__(self, vault: Path) -> None:
        self.vault = vault
        self.state: SessionState = load_session(vault)
        for pane in WIDTH_LIMITS:
            self.state.pane_widths[pane] = clamp_width(pane, self.state.pane_widths[pane])
        self._splitters: dict[str, PaneSplitter] = {}
        self._status: StatusBar | None = None
        self._save_handle: asyncio.TimerHandle | None = None

    # ---- building ------------------------------------------------------------------------

    def build(self) -> None:
        with ui.element("div").classes("pp-root"):
            outer = self._make_splitter("left", reverse=False)
            with outer.before:
                self._left_pane()
            with outer.after, ui.column().classes("pp-main"):
                inner = self._make_splitter("right", reverse=True)
                inner.classes("pp-grow")
                with inner.before:
                    self._center_pane()
                with inner.after:
                    chat_panel()
                self._status = status_bar(lambda: self.toggle("left"), lambda: self.toggle("right"))
        for pane in WIDTH_LIMITS:
            self._apply(pane)

    def _make_splitter(self, pane: str, *, reverse: bool) -> PaneSplitter:
        splitter = PaneSplitter(reverse=reverse, value=self.state.pane_widths[pane])
        splitter.props("unit=px").classes("pp-fill")
        splitter.on_value_change(lambda e, p=pane: self._on_resize(p, e.value))
        self._splitters[pane] = splitter
        return splitter

    def _left_pane(self) -> None:
        with ui.column().classes("pp-pane pp-left"), ui.column().classes("pp-pane-body"):
            ui.label("Files").classes("pp-pane-title")
            ui.label(self.vault.name).classes("pp-muted")  # tree arrives in P1.4
            ui.space()  # bottom of this pane is reserved for the profile block (P8.3)

    def _center_pane(self) -> None:
        with ui.column().classes("pp-pane pp-center"), ui.column().classes("pp-pane-body"):
            ui.label("Open a note to start writing").classes("pp-muted pp-empty")

    # ---- behaviour -----------------------------------------------------------------------

    def toggle(self, pane: str) -> None:
        self.state.panes_open[pane] = not self.state.panes_open[pane]
        self._apply(pane)
        self._save_soon(immediately=True)

    def _apply(self, pane: str) -> None:
        splitter = self._splitters[pane]
        if self.state.panes_open[pane]:
            splitter.set_limits(*WIDTH_LIMITS[pane])
            splitter.value = self.state.pane_widths[pane]
            splitter.props(remove="disable")
        else:
            splitter.set_limits(0, 0)
            splitter.value = 0
            splitter.props("disable")
        self._sync_toggles()

    def _sync_toggles(self) -> None:
        if self._status is None:
            return
        buttons = {"left": self._status.left_toggle, "right": self._status.right_toggle}
        for pane, button in buttons.items():
            if self.state.panes_open[pane]:
                button.classes(remove="pp-toggle-off")
            else:
                button.classes("pp-toggle-off")

    def _on_resize(self, pane: str, value: float | None) -> None:
        # Programmatic changes (collapse/restore) also land here; only an open pane's width counts.
        if value is None or not self.state.panes_open[pane] or value <= 0:
            return
        width = clamp_width(pane, round(value))
        if width != self.state.pane_widths[pane]:
            self.state.pane_widths[pane] = width
            self._save_soon()

    def _save_soon(self, *, immediately: bool = False) -> None:
        if self._save_handle is not None:
            self._save_handle.cancel()
            self._save_handle = None
        if immediately:
            self._save_now()
            return
        self._save_handle = asyncio.get_running_loop().call_later(SAVE_DELAY_S, self._save_now)

    def _save_now(self) -> None:
        save_session(self.vault, self.state)
