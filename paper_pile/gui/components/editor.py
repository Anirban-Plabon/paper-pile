"""NiceGUI element wrapping the CodeMirror 6 Live Preview editor.

The browser owns the buffer. Python sets text or inserts at the cursor through explicit
method calls (never reactive props, so a server push cannot clobber typing) and receives
``change`` / ``blur`` / ``save`` / ``slash_query`` / ``slash_run`` / ``table_op`` /
``image_saved`` / ``paste`` / ``print_layout`` / ``page_break`` / ``page_break_move`` events.
Events about the text carry the ``docId`` given to the last :meth:`set_text`, so a late
event from an old note is detectable.
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
        options: dict[str, Any] | None = None,
        on_change: Handler | None = None,
        on_blur: Handler | None = None,
        on_save: Handler | None = None,
        on_slash_query: Handler | None = None,
        on_slash_run: Handler | None = None,
        on_table_op: Handler | None = None,
        on_image_saved: Handler | None = None,
        on_image_error: Handler | None = None,
        on_image_resize: Handler | None = None,
        on_ai_selection: Handler | None = None,
        on_selection: Handler | None = None,
        on_block_to_chat: Handler | None = None,
        on_link: Handler | None = None,
        on_wikilink: Handler | None = None,
        on_paste: Handler | None = None,
        on_focus: Handler | None = None,
        on_tag: Handler | None = None,
        on_caret: Handler | None = None,
        on_print_layout: Handler | None = None,
        on_page_break: Handler | None = None,
        on_page_break_move: Handler | None = None,
    ) -> None:
        super().__init__()
        self._props["initialText"] = text
        self._props["mode"] = mode
        self._props["theme"] = theme
        self._props["imageUploadUrl"] = image_upload_url
        self._props["linkTarget"] = link_target  # "window": open in the page (web mode)
        self._props["options"] = options or {}
        if on_change:
            self.on("change", on_change)
        if on_focus:
            self.on("focus", on_focus)
        if on_tag:
            self.on("tag", on_tag)
        if on_caret:
            self.on("caret", on_caret)
        if on_print_layout:
            self.on("print_layout", on_print_layout)
        if on_page_break:
            self.on("page_break", on_page_break)
        if on_page_break_move:
            self.on("page_break_move", on_page_break_move)
        if on_blur:
            self.on("blur", on_blur)
        if on_save:
            self.on("save", on_save)
        if on_slash_query:
            self.on("slash_query", on_slash_query)
        if on_slash_run:
            self.on("slash_run", on_slash_run)
        if on_table_op:
            self.on("table_op", on_table_op)
        if on_image_saved:
            self.on("image_saved", on_image_saved)
        if on_image_error:
            self.on("image_error", on_image_error)
        if on_image_resize:
            self.on("image_resize", on_image_resize)
        if on_ai_selection:
            self.on("ai_selection", on_ai_selection)
        if on_selection:
            self.on("selection", on_selection)
        if on_block_to_chat:
            self.on("block_to_chat", on_block_to_chat)
        if on_link:
            self.on("link", on_link)
        if on_wikilink:
            self.on("wikilink", on_wikilink)
        if on_paste:
            self.on("paste", on_paste)

    async def get_text(self, doc_id: int) -> str | None:
        """The text of doc ``doc_id`` if it is the one on screen; ``None`` if another doc is
        shown or the browser did not answer in time."""
        try:
            text = await self.run_method("getText", doc_id)
        except TimeoutError:
            return None
        return None if text is None else str(text)

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
        self,
        doc_id: int,
        changes: list[dict[str, int | str]],
        expected: str,
        cursor: int | None = None,
    ) -> bool:
        """Apply text edits to tab ``doc_id`` keeping its undo history, as one undo step.
        ``cursor`` (a JavaScript offset in the text after the edits) moves the caret. ``False``
        means the tab no longer held ``expected`` (or the browser did not answer): nothing
        changed."""
        try:
            return bool(await self.run_method("applyChanges", doc_id, changes, expected, cursor))
        except TimeoutError:
            return False

    async def stream_begin(self, stream_id: int, pos: int) -> None:
        """Start typing an AI answer at JavaScript offset ``pos`` of the note on screen. Returns
        once the editor has set it up, so a following :meth:`stream_append` finds it."""
        try:
            await self.run_method("streamBegin", stream_id, pos)
        except TimeoutError:
            return

    async def stream_append(self, stream_id: int, text: str) -> bool:
        """Type ``text`` into the stream; ``False`` means the stream is gone (other note shown)."""
        try:
            return bool(await self.run_method("streamAppend", stream_id, text))
        except TimeoutError:
            return False

    def stream_end(self, stream_id: int) -> None:
        self.run_method("streamEnd", stream_id)

    async def get_selection(self) -> tuple[str, int, int] | None:
        """The selected text and its JavaScript offsets ``(text, from, to)``; ``None`` if the
        browser did not answer. An empty selection gives ``("", n, n)``."""
        try:
            sel = await self.run_method("getSelection")
        except TimeoutError:
            return None
        return (str(sel["text"]), int(sel["from"]), int(sel["to"])) if sel else None

    def pick_image(self) -> None:
        """Open the browser's file chooser; the chosen images are uploaded and reported back as
        ``image_saved`` events."""
        self.run_method("pickImage")

    def focus_table_cell(self, row: int, col: int, start: int | None = None) -> None:
        """Put the cursor in a table cell (row 0 = header). ``start`` is the table's offset in
        the text (a JavaScript offset); without it the next table update that has the cell wins."""
        self.run_method("focusTableCell", row, col, start)

    def set_slash_results(self, seq: int, groups: list[dict[str, Any]]) -> None:
        """The commands matching query number ``seq`` (see ``groups_json``)."""
        self.run_method("setSlashResults", seq, groups)

    def set_known_notes(self, names: list[str]) -> None:
        """Names wikilinks may use for existing notes; other links get the "missing" look."""
        self.run_method("setKnownNotes", names)

    def goto_line(self, line: int) -> None:
        """Put the caret on a 1-based line of the shown note and scroll it to the top."""
        self.run_method("gotoLine", line)

    def insert_at_cursor(self, text: str) -> None:
        self.run_method("insertAtCursor", text)

    def set_options(self, options: dict[str, Any]) -> None:
        """``wordWrap`` / ``tabSize`` / ``spellCheck`` for every open note (Settings)."""
        self.run_method("setOptions", options)

    def set_mode(self, mode: Mode) -> None:
        self.run_method("setMode", mode)

    def set_theme(self, theme: Theme) -> None:
        self.run_method("setTheme", theme)

    def focus(self) -> None:
        self.run_method("focus")

    def sync_text(self, doc_id: int, text: str) -> None:
        """The note ``doc_id`` changed in the other editor of a split: mirror it here (outside
        this editor's undo history, not reported back as a change)."""
        self.run_method("syncText", doc_id, text)

    def print_layout_ready(self, seq: int, url: str) -> None:
        """The print page for page view's request ``seq`` (see ``static/print.js``)."""
        self.run_method("printLayoutReady", seq, url)

    def open_search(self, replace: bool = False, query: str = "") -> None:
        """Find (``replace``: and replace) in the note on screen; ``query`` fills the search box
        and selects its first match."""
        self.run_method("openSearch", replace, query)
