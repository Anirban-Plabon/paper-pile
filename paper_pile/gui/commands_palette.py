"""The command palette's list (Ctrl+P, PLAN §4.18): every app action with its shortcut.

A command is listed only when it makes sense now (``when``): note commands need an open note,
AI commands the AI feature, and so on. Matching is ``core.commands.match_score`` over the title
and a few extra words.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nicegui import background_tasks

from paper_pile.core.commands import match_score
from paper_pile.core.settings import feature_on
from paper_pile.gui.components.picker_popup import PickItem

if TYPE_CHECKING:
    from paper_pile.gui.layout import MainLayout


@dataclass(frozen=True, slots=True)
class PaletteCommand:
    id: str
    title: str
    run: Callable[[], Any]  # may return an awaitable
    keys: str = ""
    icon: str = ""
    words: str = ""  # more words it is found by
    when: Callable[[], bool] = lambda: True


def palette_commands(layout: "MainLayout") -> list[PaletteCommand]:
    pane = layout.editor_pane
    assert pane is not None
    actions = pane.note_actions

    def note() -> bool:
        return pane.active_note() is not None

    def ai() -> bool:
        return layout.ai_on()

    def ai_note() -> bool:
        return ai() and note()

    def calendar() -> bool:
        return feature_on(layout.config.values, "features.calendar")

    def switch(key: str) -> Callable[[], None]:
        return lambda: layout.settings.set_value(key, not feature_on(layout.config.values, key))

    def theme(value: str) -> Callable[[], None]:
        return lambda: layout.settings.set_value("appearance.theme", value)

    C = PaletteCommand
    return [
        C("open-note", "Open note…", layout.open_note, "Ctrl+O", "search", "switcher go to file"),
        C("new-note", "New note", layout.new_note, "Ctrl+N", "file-plus", "create"),
        C("new-folder", "New folder", layout.new_folder, "", "folder-plus", "create"),
        C(
            "search",
            "Search in all notes",
            layout.search_vault,
            "Ctrl+Shift+F",
            "text-search",
            "find full text",
        ),
        C(
            "toggle-left",
            "Show / hide file tree",
            lambda: layout.toggle("left"),
            "Ctrl+B",
            "panel-left",
            "sidebar files",
        ),
        C(
            "toggle-right",
            "Show / hide right pane",
            lambda: layout.toggle("right"),
            "Ctrl+L",
            "panel-right",
            "chat calendar side",
            when=lambda: layout.right is not None and layout.right.has_tabs(),
        ),
        C("settings", "Settings", layout.open_settings, "Ctrl+,", "settings", "preferences"),
        C("open-vault", "Open vault…", layout.open_vault, "", "folder-open", "switch folder"),
        C("trash", "Open trash", layout.open_trash, "", "trash", "restore deleted bin"),
        C("close-tab", "Close tab", layout.close_tab, "Ctrl+W", "x", when=note),
        C(
            "next-tab",
            "Next tab",
            lambda: layout.cycle_tabs(1),
            "Ctrl+Tab",
            "arrow-right",
            when=note,
        ),
        C(
            "prev-tab",
            "Previous tab",
            lambda: layout.cycle_tabs(-1),
            "Ctrl+Shift+Tab",
            "arrow-left",
            when=note,
        ),
        C(
            "mode",
            "Switch Live / Source",
            layout.toggle_mode,
            "Ctrl+E",
            "code",
            "preview",
            when=note,
        ),
        C(
            "tidy",
            "Tidy note",
            layout.tidy_note,
            "Shift+Alt+F",
            "brush-cleaning",
            "format",
            when=note,
        ),
        C("find", "Find in note", actions.find, "Ctrl+F", "search", when=note),
        C("replace", "Replace in note", actions.replace, "Ctrl+H", "replace", when=note),
        C("split", "Split right / close split", actions.toggle_split, "", "columns-2", when=note),
        C(
            "page-view",
            "Page view on / off",
            actions.toggle_page_view,
            "",
            "file-text",
            "print pages",
            when=note,
        ),
        C(
            "outline",
            "Outline",
            layout.toggle_outline,
            "Ctrl+Shift+O",
            "list-tree",
            "headings contents",
            when=note,
        ),
        C("move", "Move note to…", actions.move, "", "folder-input", when=note),
        C("merge", "Merge note into…", actions.merge, "", "merge", when=note),
        C("copy-path", "Copy note path", actions.copy_path, "", "link", when=note),
        C("export-md", "Export as Markdown", actions.export_markdown, "", "file-down", when=note),
        C("export-html", "Export as HTML", actions.export_html, "", "file-code", when=note),
        C("export-pdf", "Export as PDF", actions.export_pdf, "", "printer", "print", when=note),
        C("ask-ai", "Ask AI", layout.ask_ai, "", "sparkles", "chat", when=ai),
        C(
            "add-to-chat",
            "Add note to chat",
            actions.add_to_chat,
            "",
            "message-square-plus",
            when=ai_note,
        ),
        C(
            "summarize",
            "Summarize note",
            actions.summarize,
            "",
            "list-collapse",
            "ai",
            when=ai_note,
        ),
        C(
            "calendar",
            "Show calendar",
            layout.show_calendar,
            "",
            "calendar",
            "daily notes",
            when=calendar,
        ),
        C("theme-light", "Light mode", theme("light"), "", "sun", "theme"),
        C("theme-dark", "Dark mode", theme("dark"), "", "moon", "theme"),
        C("theme-system", "System mode", theme("system"), "", "monitor", "theme"),
        C("feature-ai", "Turn AI on / off", switch("features.ai"), "", "sparkles", "feature"),
        C(
            "feature-calendar",
            "Turn calendar on / off",
            switch("features.calendar"),
            "",
            "calendar",
            "feature",
        ),
    ]


def palette_items(commands: list[PaletteCommand], query: str) -> list[PickItem]:
    """The commands available now that match ``query``, best first (list order on ties)."""
    scored: list[tuple[int, int, PaletteCommand]] = []
    for i, cmd in enumerate(commands):
        if not cmd.when():
            continue
        by_title = match_score(query, cmd.title)
        by_words = match_score(query, cmd.words)
        scores = [
            s for s in (by_title, None if by_words is None else by_words - 10) if s is not None
        ]
        if scores:
            scored.append((-max(scores), i, cmd))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [PickItem(c.id, c.title, hint=c.keys, icon=c.icon) for _s, _i, c in scored]


def run_command(commands: list[PaletteCommand], command_id: str) -> None:
    for cmd in commands:
        if cmd.id == command_id:
            result = cmd.run()
            if inspect.isawaitable(result):
                background_tasks.create(result)  # type: ignore[arg-type]
            return
