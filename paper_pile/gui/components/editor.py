"""NiceGUI element wrapping the CodeMirror 6 Live Preview editor.

The browser owns the buffer. Python sets text or inserts at the cursor through explicit
method calls (never reactive props, so a server push cannot clobber typing) and receives
``change`` / ``blur`` / ``save`` / ``slash`` / ``paste`` events. Events about the text carry the
``docId`` given to the last :meth:`set_text`, so a late event from an old note is detectable.
"""

from collections.abc import Callable
from typing import Any, Literal

from nicegui import events
from nicegui.element import Element

Mode = Literal["live", "source"]
Theme = Literal["light", "dark"]
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
        theme: Theme = "light",
        image_upload_url: str | None = None,
        link_target: Literal["window", "python"] = "python",
        on_change: Handler | None = None,
        on_blur: Handler | None = None,
        on_save: Handler | None = None,
        on_slash: Handler | None = None,
        on_link: Handler | None = None,
        on_wikilink: Handler | None = None,
        on_paste: Handler | None = None,
    ) -> None:
        super().__init__()
        self._props["initialText"] = text
        self._props["mode"] = mode
        self._props["theme"] = theme
        self._props["imageUploadUrl"] = image_upload_url
        self._props["linkTarget"] = link_target  # "window": open in the page (web mode)
        if on_change:
            self.on("change", on_change)
        if on_blur:
            self.on("blur", on_blur)
        if on_save:
            self.on("save", on_save)
        if on_slash:
            self.on("slash", on_slash)
        if on_link:
            self.on("link", on_link)
        if on_wikilink:
            self.on("wikilink", on_wikilink)
        if on_paste:
            self.on("paste", on_paste)

    async def get_text(self) -> str | None:
        """The editor's current text, or ``None`` if the browser did not answer in time."""
        try:
            return str(await self.run_method("getText"))
        except TimeoutError:
            return None

    def set_text(
        self, text: str, doc_id: int = 0, path: str = "", *, keep_caret: bool = False
    ) -> None:
        """Replace the document (and reset undo history). ``doc_id`` tags later events;
        ``path`` is the note's vault path (images are resolved relative to it);
        ``keep_caret`` leaves the caret where it was (a reload of an outside change)."""
        self.run_method("setText", text, doc_id, path, keep_caret)

    def show_doc(self, doc_id: int, text: str, path: str = "") -> None:
        """Switch to tab ``doc_id``: its parked editor state if it has one, else ``text``."""
        self.run_method("showDoc", doc_id, text, path)

    def set_path(self, path: str) -> None:
        """The shown note was renamed or moved."""
        self.run_method("setPath", path)

    def close_doc(self, doc_id: int) -> None:
        """Forget the parked editor state of a closed tab."""
        self.run_method("closeDoc", doc_id)

    async def apply_changes(
        self, doc_id: int, changes: list[dict[str, int | str]], expected: str
    ) -> bool:
        """Apply text edits to tab ``doc_id`` keeping its undo history. ``False`` means the tab
        no longer held ``expected`` (or the browser did not answer) and nothing was changed."""
        try:
            return bool(await self.run_method("applyChanges", doc_id, changes, expected))
        except TimeoutError:
            return False

    def set_known_notes(self, names: list[str]) -> None:
        """Names wikilinks may use for existing notes; other links get the "missing" look."""
        self.run_method("setKnownNotes", names)

    def goto_line(self, line: int) -> None:
        """Put the caret on a 1-based line of the shown note and scroll it to the top."""
        self.run_method("gotoLine", line)

    def insert_at_cursor(self, text: str) -> None:
        self.run_method("insertAtCursor", text)

    def set_mode(self, mode: Mode) -> None:
        self.run_method("setMode", mode)

    def set_theme(self, theme: Theme) -> None:
        self.run_method("setTheme", theme)

    def focus(self) -> None:
        self.run_method("focus")
