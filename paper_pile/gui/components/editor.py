"""NiceGUI element wrapping the CodeMirror 6 Live Preview editor.

The browser owns the buffer. Python sets text or inserts at the cursor through explicit
method calls (never reactive props, so a server push cannot clobber typing) and receives
``change`` / ``slash`` / ``paste`` events.
"""

from collections.abc import Callable
from typing import Any, Literal

from nicegui import events
from nicegui.element import Element

Mode = Literal["live", "source"]
Handler = Callable[[events.GenericEventArguments], Any]


class Editor(
    Element,
    component="pp_editor.js",
    esm={"pp-editor": "../static/vendor/pp-editor"},
):
    def __init__(
        self,
        text: str = "",
        *,
        mode: Mode = "live",
        image_upload_url: str | None = None,
        on_change: Handler | None = None,
        on_slash: Handler | None = None,
        on_paste: Handler | None = None,
    ) -> None:
        super().__init__()
        self._props["initialText"] = text
        self._props["mode"] = mode
        self._props["imageUploadUrl"] = image_upload_url
        if on_change:
            self.on("change", on_change)
        if on_slash:
            self.on("slash", on_slash)
        if on_paste:
            self.on("paste", on_paste)

    async def get_text(self) -> str:
        return str(await self.run_method("getText"))

    def set_text(self, text: str) -> None:
        self.run_method("setText", text)

    def insert_at_cursor(self, text: str) -> None:
        self.run_method("insertAtCursor", text)

    def set_mode(self, mode: Mode) -> None:
        self.run_method("setMode", mode)

    def focus(self) -> None:
        self.run_method("focus")
