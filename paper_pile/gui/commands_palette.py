"""The command palette's list (Ctrl+P, PLAN §4.18): every app action with its shortcut.

A command is listed only when it makes sense now (``when``): note commands need an open note,
AI commands the AI feature, and so on. Matching is ``core.commands.match_score`` over the title
and a few extra words.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from nicegui import background_tasks

from paper_pile.core.ai.commands import AI_COMMANDS
from paper_pile.core.commands import match_score
from paper_pile.core.settings import feature_on, sanitized
from paper_pile.gui.components.picker_popup import PickItem

if TYPE_CHECKING:
    from paper_pile.gui.layout import MainLayout


# The palette's groups, in the order they are listed.
GROUPS = ("Notes", "Tabs", "Editing", "Export", "AI", "View", "App")


@dataclass(frozen=True, slots=True)
class PaletteCommand:
    id: str
    title: str
    run: Callable[[], Any]  # may return an awaitable
    keys: str = ""
    icon: str = ""
    words: str = ""  # more words it is found by
    when: Callable[[], bool] = lambda: True
    group: str = "App"


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

    def toggle(key: str) -> Callable[[], None]:
        """Flip an on/off setting (its current value, default included)."""
        return lambda: layout.settings.set_value(key, not sanitized(layout.config.values)[key])

    def setting(key: str, value: str) -> Callable[[], None]:
        return lambda: layout.settings.set_value(key, value)

    def with_note(run: Callable[[str], Any]) -> Callable[[], Any]:
        def go() -> Any:
            path = pane.active_note()
            return run(path) if path is not None else None

        return go

    def g(group: str, *commands: "PaletteCommand") -> list["PaletteCommand"]:
        return [replace(c, group=group) for c in commands]

    C = PaletteCommand
    return [
        *g(
            "Notes",
            C("open-note", "Open note…", layout.open_note, "Ctrl+O", "search", "switcher go to"),
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
                "daily",
                "Open today's daily note",
                layout.open_today,
                "",
                "calendar-days",
                "journal date today",
                when=calendar,
            ),
            C(
                "rename",
                "Rename note…",
                with_note(lambda p: layout.bus.publish("note.rename", path=p)),
                "",
                "pencil",
                when=note,
            ),
            C("move", "Move note to…", actions.move, "", "folder-input", when=note),
            C("merge", "Merge note into…", actions.merge, "", "merge", when=note),
            C(
                "reveal",
                "Show note in file tree",
                with_note(lambda p: layout.bus.publish("note.reveal", path=p)),
                "",
                "locate",
                "reveal locate",
                when=note,
            ),
            C("copy-path", "Copy note path", actions.copy_path, "", "link", when=note),
            C(
                "copy-full-path",
                "Copy full file path",
                actions.copy_full_path,
                "",
                "clipboard-copy",
                "absolute disk",
                when=note,
            ),
            C(
                "history",
                "Version history",
                layout.open_history,
                "",
                "history",
                "versions undo restore earlier",
                when=note,
            ),
            C("trash", "Open trash", layout.open_trash, "", "trash", "restore deleted bin"),
        ),
        *g(
            "Tabs",
            C("close-tab", "Close tab", layout.close_tab, "Ctrl+W", "x", when=note),
            C(
                "close-others",
                "Close other tabs",
                pane.close_other_tabs,
                "",
                "copy-x",
                when=lambda: len(pane.tabs.tabs) > 1,
            ),
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
                "split",
                "Split right / close split",
                actions.toggle_split,
                "",
                "columns-2",
                when=note,
            ),
        ),
        *g(
            "Editing",
            C(
                "mode",
                "Switch Live / Source",
                layout.toggle_mode,
                "Ctrl+E",
                "code",
                "preview",
                when=note,
            ),
            C("find", "Find in note", actions.find, "Ctrl+F", "search", when=note),
            C("replace", "Replace in note", actions.replace, "Ctrl+H", "replace", when=note),
            C(
                "tidy",
                "Tidy note",
                layout.tidy_note,
                "Shift+Alt+F",
                "brush-cleaning",
                "format",
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
            C(
                "page-view",
                "Page view on / off",
                actions.toggle_page_view,
                "",
                "file-text",
                "print pages",
                when=note,
            ),
        ),
        *g(
            "Export",
            C(
                "export-md",
                "Export as Markdown",
                actions.export_markdown,
                "",
                "file-down",
                when=note,
            ),
            C("export-html", "Export as HTML", actions.export_html, "", "file-code", when=note),
            C("export-pdf", "Export as PDF", actions.export_pdf, "", "printer", "print", when=note),
        ),
        *g(
            "AI",
            C("ask-ai", "Ask AI", layout.ask_ai, "", "sparkles", "chat", when=ai),
            C(
                "new-chat",
                "New chat",
                layout.new_chat,
                "",
                "square-pen",
                "ai conversation",
                when=ai,
            ),
            C(
                "add-to-chat",
                "Add note to chat",
                actions.add_to_chat,
                "",
                "sparkles",
                when=ai_note,
            ),
            # the one AI command list (PLAN §4.28): each opens the Ask box with it picked
            *(
                C(
                    c.id,
                    c.title,
                    lambda i=c.id: pane.run_ai_command(i),
                    "",
                    c.icon,
                    " ".join(("ai", *c.aliases)),
                    when=ai_note,
                )
                for c in AI_COMMANDS
            ),
            C("write", "Write with AI…", actions.write, "", "pen-line", "ai", when=ai_note),
        ),
        *g(
            "View",
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
            C(
                "calendar",
                "Show calendar",
                layout.show_calendar,
                "",
                "calendar",
                "daily notes",
                when=calendar,
            ),
            C(
                "line-numbers",
                "Line numbers on / off",
                toggle("editor.line_numbers"),
                "",
                "list-ordered",
                "gutter",
            ),
            C("word-wrap", "Wrap long lines on / off", toggle("editor.word_wrap"), "", "wrap-text"),
            C(
                "readable",
                "Readable line length on / off",
                toggle("editor.readable_width"),
                "",
                "text",
                "width narrow",
            ),
            C(
                "highlight-line",
                "Highlight current line on / off",
                toggle("editor.highlight_line"),
                "",
                "highlighter",
                "active caret",
            ),
            C(
                "theme-light",
                "Light mode",
                setting("appearance.theme", "light"),
                "",
                "sun",
                "theme",
            ),
            C("theme-dark", "Dark mode", setting("appearance.theme", "dark"), "", "moon", "theme"),
            C(
                "theme-system",
                "System mode",
                setting("appearance.theme", "system"),
                "",
                "monitor",
                "theme",
            ),
            C(
                "motion-off",
                "Animations off",
                setting("appearance.motion", "off"),
                "",
                "pause",
                "motion speed reduce",
            ),
            C(
                "motion-on",
                "Animations on",
                setting("appearance.motion", "normal"),
                "",
                "play",
                "motion speed",
            ),
        ),
        *g(
            "App",
            C("settings", "Settings", layout.open_settings, "Ctrl+,", "settings", "preferences"),
            C("open-vault", "Open vault…", layout.open_vault, "", "folder-open", "switch folder"),
            C(
                "rebuild-index",
                "Rebuild search index",
                layout.rebuild_index_now,
                "",
                "refresh-cw",
                "cache backlinks tags",
            ),
            C("feature-ai", "Turn AI on / off", switch("features.ai"), "", "sparkles", "feature"),
            C(
                "feature-calendar",
                "Turn calendar on / off",
                switch("features.calendar"),
                "",
                "calendar",
                "feature",
            ),
        ),
    ]


def palette_items(commands: list[PaletteCommand], query: str) -> list[PickItem]:
    """The commands available now that match ``query``, under their group headings. Empty
    query: every group in order, each in list order. Otherwise the groups are ordered by their
    best match and each lists its matches best first (list order on ties)."""
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
    rank = {name: n for n, name in enumerate(GROUPS)}
    best: dict[str, int] = {}
    for score, _i, cmd in scored:
        best[cmd.group] = min(best.get(cmd.group, 0), score)
    if query.strip():
        scored.sort(key=lambda t: (best[t[2].group], rank.get(t[2].group, 99), t[0], t[1]))
    else:
        scored.sort(key=lambda t: (rank.get(t[2].group, 99), t[1]))
    return [
        PickItem(c.id, c.title, hint=c.keys, icon=c.icon, group=c.group) for _s, _i, c in scored
    ]


def run_command(commands: list[PaletteCommand], command_id: str) -> None:
    for cmd in commands:
        if cmd.id == command_id:
            result = cmd.run()
            if inspect.isawaitable(result):
                background_tasks.create(result)  # type: ignore[arg-type]
            return
