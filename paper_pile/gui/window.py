"""Window chrome for the native window: it has no OS title bar, so the tab rows are the title bar.

The page only captures the mouse (``static/window.js``); moving and resizing are handed to the
compositor (``native_boot.py``), which is the only way that works on Wayland. In ``--serve`` mode
none of this exists.
"""

import logging
import queue
from typing import Any

from nicegui import app, run, ui
from nicegui.native import native

from paper_pile.gui.icons import icon_button, line_icon

log = logging.getLogger("paper_pile.window")

EDGE_STRIPS = ("n", "s", "e", "w", "ne", "nw", "se", "sw")


async def native_request(method: str, *args: Any, timeout: float = 120) -> Any:
    """Call a method ``native_boot`` added to the window (it runs in the window's process) and wait
    for its answer; ``None`` outside the native window or when it does not answer in time."""
    if native.method_queue is None or native.response_queue is None:
        return None
    method_queue, response_queue = native.method_queue, native.response_queue

    def call() -> Any:
        method_queue.put((method, args, {}))
        try:
            return response_queue.get(timeout=timeout)
        except queue.Empty:
            log.warning("the window did not answer %s in time", method)
            return None

    return await run.io_bound(call)


class WindowChrome:
    """The window's state is the page's ``body.pp-maximized`` (kept by ``native_boot``): the
    maximize button shows a square or two squares from it, and its click says which it saw."""

    def build(self) -> None:
        """The three buttons (top right) and the resize edges; call inside the page."""
        with ui.row().classes("pp-wincontrols items-center no-wrap"):
            icon_button("minus", lambda: self._do("minimize"), "Minimize")
            toggle = icon_button("square", lambda: None, "Maximize / restore").classes("pp-win-max")
            toggle.on(
                "click",
                js_handler="() => emitEvent('pp_win', {op: 'maximize', "
                "max: document.body.classList.contains('pp-maximized')})",
            )
            with toggle:
                line_icon("copy", "s").classes("pp-win-restore")  # shown while maximized
            icon_button("x", lambda: self._do("destroy"), "Close").classes("pp-win-close")
        for edge in EDGE_STRIPS:
            ui.element("div").classes(f"pp-resize pp-resize-{edge}").props(f'data-edge="{edge}"')
        ui.on("pp_win", self._on_event)

    def _do(self, method: str) -> None:
        window = app.native.main_window
        if window is not None:
            getattr(window, method)()

    def _on_event(self, e: Any) -> None:
        op = str(e.args["op"])
        maximized = bool(e.args.get("max"))
        if op == "maximize":
            self._do("restore" if maximized else "maximize")
        elif op == "gesture" and native.method_queue is not None and not maximized:
            native.method_queue.put(("start_system_gesture", (str(e.args["edge"]),), {}))
