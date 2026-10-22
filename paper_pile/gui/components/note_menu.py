"""The ⋯ menu at the end of the tab strip: what can be done with the note on screen
(PLAN §4.15). Pure presentation: every item calls back into the editor pane, which owns the
note, the vault and the chat hand-off."""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nicegui import background_tasks, ui

from paper_pile.gui.icons import icon_button, line_icon

Action = Callable[[], Any]  # may return an awaitable


@dataclass(frozen=True, slots=True)
class NoteActions:
    find: Action
    replace: Action
    tidy: Action
    toggle_split: Action
    toggle_page_view: Action
    outline: Action
    history: Action
    move: Action
    merge: Action
    add_to_chat: Action
    summarize: Action
    rewrite: Action
    write: Action
    copy_path: Action
    copy_full_path: Action
    export_markdown: Action
    export_html: Action
    export_pdf: Action


class NoteMenu:
    def __init__(self, actions: NoteActions) -> None:
        self._actions = actions
        self._button: ui.button
        self._split_label: ui.label
        self._page_view_check: ui.element
        self._last_item: ui.menu_item
        self._ai_parts: list[ui.element] = []  # the AI group, hidden while AI is off

    def build(self) -> None:
        a = self._actions
        self._button = icon_button("ellipsis", lambda: None, "More options", size="m")
        with self._button, ui.menu().props('anchor="bottom right" self="top right"') as menu:
            menu.classes("pp-note-menu")
            self._item("search", "Find…", a.find, "Ctrl+F")
            self._item("replace", "Replace…", a.replace, "Ctrl+H")
            self._item("brush-cleaning", "Tidy note", a.tidy, "Shift+Alt+F")
            ui.separator()
            self._split_label = self._item("columns-2", "Split right", a.toggle_split)
            self._item("file-text", "Page view", a.toggle_page_view)
            with self._last_item:  # a check mark while page view is on
                self._page_view_check = line_icon("check", "s").classes(
                    "pp-note-menu-check pp-check"
                )
                self._page_view_check.set_visibility(False)
            self._item("list-tree", "Outline", a.outline, "Ctrl+Shift+O")
            self._item("history", "Version history", a.history)
            self._item("folder-input", "Move to…", a.move)
            self._item("merge", "Merge into…", a.merge)
            self._ai_parts.append(ui.separator())
            self._ai_parts.append(ui.label("AI").classes("pp-note-menu-group"))
            for icon, label, action in (
                ("message-square-plus", "Add to chat", a.add_to_chat),
                ("list-collapse", "Summarize", a.summarize),
                ("wand-sparkles", "Rewrite", a.rewrite),
                ("pen-line", "Write…", a.write),
            ):
                self._item(icon, label, action)
                self._ai_parts.append(self._last_item)
            ui.separator()
            self._item("link", "Copy path", a.copy_path)
            self._item("clipboard-copy", "Copy full path", a.copy_full_path)
            self._item("file-down", "Export as Markdown", a.export_markdown)
            self._item("file-code", "Export as HTML", a.export_html)
            self._item("printer", "Export as PDF", a.export_pdf)
            self._item("external-link", "Open in default app", None, "Soon")

    def set_ai(self, on: bool) -> None:
        """Show the AI group only while the AI feature is on."""
        for part in self._ai_parts:
            part.set_visibility(on)

    def update(self, *, has_note: bool, split_open: bool, page_view: bool) -> None:
        """Hide the button without a note; the split item names what it will do."""
        self._button.set_visibility(has_note)
        self._split_label.set_text("Close split" if split_open else "Split right")
        self.set_page_view(page_view)

    def set_page_view(self, on: bool) -> None:
        self._page_view_check.set_visibility(on)

    def _item(self, icon: str, label: str, action: Action | None, hint: str = "") -> ui.label:
        def run() -> None:
            if action is None:
                return
            result = action()
            if inspect.isawaitable(result):
                background_tasks.create(result)  # type: ignore[arg-type]

        item = ui.menu_item(on_click=run).classes("pp-note-menu-item").mark(label)
        self._last_item = item
        if action is None:
            item.props("disable")
        with item:
            line_icon(icon).classes("pp-note-menu-icon")
            text = ui.label(label).classes("pp-note-menu-label")
            if hint:
                ui.label(hint).classes("pp-note-menu-hint")
        return text
