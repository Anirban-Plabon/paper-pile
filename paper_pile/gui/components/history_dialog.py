"""The Version history popup (PLAN §4.18): a note's earlier versions, newest first.

Left: when each was kept, why, and how many lines it differs from the note now. Right: the
picked version as changes against the note now, or as plain text; *Restore* (an undoable edit,
the current text kept first) and *Copy*. Versions come from ``core.history``; a version that
cannot be rebuilt exactly says so instead of showing text.
"""

import difflib
from collections.abc import Awaitable, Callable
from datetime import datetime

from nicegui import ui

from paper_pile.core.history import DamagedVersion, History, Version
from paper_pile.gui.components.trash_dialog import when
from paper_pile.gui.icons import close_button

MAX_DIFF_LINES = 600  # lines drawn in the Changes view


def counts(old: str, new: str) -> tuple[int, int]:
    """(lines added, lines removed) going from ``old`` to ``new``."""
    added = removed = 0
    for line in difflib.ndiff(old.splitlines(), new.splitlines()):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return added, removed


def diff_lines(old: str, new: str) -> list[tuple[str, str]]:
    """The changes from ``old`` to ``new`` as (kind, line): kind is ``+``, ``-``, `` `` or ``@``
    (a gap between changed parts); two lines of context around each change."""
    out: list[tuple[str, str]] = []
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), n=2, lineterm="")
    for line in list(diff)[2:]:  # skip the ---/+++ header
        kind = line[:1]
        out.append(("@", "…") if kind == "@" else (kind, line[1:]))
    return out


class HistoryDialog:
    def __init__(
        self,
        history: History,
        host: ui.element,
        path: str,
        current: str,
        restore: Callable[[str], Awaitable[bool]],
    ) -> None:
        self.history = history
        self._host = host
        self.path = path
        self._current = current
        self._restore = restore
        self._versions: list[tuple[Version, str | DamagedVersion]] = []
        self._picked = 0
        self._view = "changes"
        self._rows: list[ui.element] = []
        self._detail: ui.column
        self._dialog: ui.dialog

    async def open(self) -> None:
        self._versions = self.history.all_texts(self.path)
        name = self.path.rsplit("/", 1)[-1]
        with self._host, ui.dialog() as dialog, ui.card().classes("pp-dialog pp-history"):
            self._dialog = dialog
            with ui.row().classes("items-center no-wrap w-full"):
                ui.label(f"Version history — {name}").classes("pp-dialog-title")
                ui.space()
                close_button(dialog.close)
            if not self._versions:
                ui.label(
                    "No earlier versions yet. One is kept when you start editing the note, and "
                    "before AI, Tidy or a merge change it."
                ).classes("pp-muted")
            else:
                with ui.row().classes("pp-history-body no-wrap"):
                    with ui.column().classes("pp-history-list"):
                        self._list()
                    self._detail = ui.column().classes("pp-history-detail")
                self._show()
        dialog.open()
        await dialog
        dialog.delete()

    def _list(self) -> None:
        now = datetime.now()
        for i, (version, text) in enumerate(self._versions):
            row = ui.column().classes("pp-history-row")
            with row:
                ui.label(when(datetime.fromtimestamp(version.ts), now)).classes("pp-history-when")
                if isinstance(text, DamagedVersion):
                    detail = "damaged"
                else:
                    added, removed = counts(self._current, text)  # what restoring it does
                    detail = "same as now" if text == self._current else f"+{added} −{removed}"
                ui.label(f"{version.reason.capitalize()} · {detail}").classes(
                    "pp-muted pp-history-why"
                )
            row.on("click", lambda _e, i=i: self._pick(i))
            self._rows.append(row)

    def _pick(self, index: int) -> None:
        self._picked = index
        self._show()

    def _set_view(self, view: str) -> None:
        self._view = view
        self._show()

    def _show(self) -> None:
        for i, row in enumerate(self._rows):
            if i == self._picked:
                row.classes("pp-history-on")
            else:
                row.classes(remove="pp-history-on")
        version, text = self._versions[self._picked]
        self._detail.clear()
        with self._detail:
            with ui.row().classes("items-center no-wrap w-full pp-history-bar"):
                for key, label in (("changes", "Changes"), ("text", "Text")):
                    button = ui.button(
                        label, on_click=lambda _e, k=key: self._set_view(k), color=None
                    )
                    button.props("flat dense no-caps").classes("pp-history-tab")
                    if key == self._view:
                        button.classes("pp-history-tab-on")
                ui.space()
                if isinstance(text, str):
                    copy = ui.button("Copy", on_click=lambda _e, t=text: self._copy(t), color=None)
                    copy.props("flat dense no-caps")
                    ui.button(
                        "Restore", on_click=lambda _e, t=text, v=version: self._do_restore(t, v)
                    ).props("dense no-caps unelevated").classes("pp-history-restore")
            with ui.element("div").classes("pp-history-view"):
                if isinstance(text, DamagedVersion):
                    ui.label("This version is damaged and cannot be shown.").classes("pp-muted")
                elif self._view == "text":
                    ui.label(text or "(empty)").classes("pp-history-text")
                else:
                    self._changes(text)

    def _changes(self, text: str) -> None:
        if text == self._current:
            ui.label("This version is the same as the note now.").classes("pp-muted")
            return
        ui.label("What restoring it would change in the note now:").classes(
            "pp-muted pp-history-hint"
        )
        lines = diff_lines(self._current, text)
        for kind, line in lines[:MAX_DIFF_LINES]:
            css = {"+": "pp-diff-add", "-": "pp-diff-del", "@": "pp-diff-gap"}.get(kind, "")
            ui.label(line or " ").classes(f"pp-diff-line {css}")
        if len(lines) > MAX_DIFF_LINES:
            ui.label(f"… {len(lines) - MAX_DIFF_LINES} more lines").classes("pp-muted")

    def _copy(self, text: str) -> None:
        ui.clipboard.write(text)
        ui.notify("Copied")

    async def _do_restore(self, text: str, version: Version) -> None:
        if await self._restore(text):
            stamp = when(datetime.fromtimestamp(version.ts), datetime.now())
            ui.notify(f"Restored the version from {stamp} (Ctrl+Z undoes it)")
            self._dialog.close()
        else:
            ui.notify("Could not restore it: open the note first.", type="negative")
