"""AI access in the UI (PLAN §4.26): the "Allow the AI to read this vault?" question on first
use, and Settings → AI → Access (this vault's grant, file types, outside paths, exclusions).

The rules and ``ai_access.json`` live in :mod:`paper_pile.core.ai.access`; the engine enforces
them. Rows use the Settings page's own classes, so the group looks like the others.
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from nicegui import ui

from paper_pile.core.ai.access import (
    Grant,
    load_grant,
    parse_types,
    save_grant,
    unique,
)
from paper_pile.core.ai.engine import AiEngine
from paper_pile.gui.dialog import Dialog
from paper_pile.gui.icons import icon_button


async def confirm_access(ai: AiEngine, host: ui.element) -> bool:
    """Ask once per vault before the AI reads it; True when it may (now or already)."""
    if ai.has_access():
        return True
    with host, Dialog() as dialog, ui.card().classes("pp-dialog pp-access-ask"):
        ui.label("Allow the AI to read this vault?").classes("pp-dialog-title")
        ui.label(
            f"To answer, the AI reads the notes of “{ai.vault.root.name}” on this computer. "
            "Limit or take it back any time in Settings → AI → Access."
        ).classes("pp-muted")
        with ui.row().classes("justify-end w-full"):
            ui.button("Not now", on_click=lambda: dialog.submit(False)).props("flat no-caps")
            ui.button("Allow", on_click=lambda: dialog.submit(True)).props("no-caps")
    dialog.open()
    allowed = bool(await dialog)
    dialog.delete()
    if allowed:
        ai.allow()
    return allowed


def _when(stamp: str) -> str:
    try:
        return datetime.fromisoformat(stamp).strftime("%b %d, %Y").replace(" 0", " ")
    except ValueError:
        return stamp


class AccessPanel:
    """Settings → AI → Access, drawn by the Settings page after its Model group."""

    def __init__(self, ai: AiEngine, access_dir: Path | None = None) -> None:
        self.ai = ai
        self._dir = access_dir

    def build(self, open_box: Callable[[str], ui.element]) -> None:
        """Draw the group (``open_box``: the Settings page's titled box)."""
        with open_box("Access"):
            self._rows()

    def _grant(self) -> Grant | None:
        return load_grant(self.ai.vault.root, self._dir)

    def _save(self, grant: Grant) -> None:
        save_grant(self.ai.vault.root, grant, self._dir)
        self.ai.access_changed()
        self._rows.refresh()

    @ui.refreshable_method
    def _rows(self) -> None:
        grant = self._grant()
        with ui.row().classes("pp-set-row items-center"):
            with ui.column().classes("pp-set-text"):
                ui.label("Read this vault").classes("pp-set-label")
                help_text = (
                    f"Allowed {_when(grant.granted)}" if grant else "Not yet: asked on first use"
                )
                ui.label(help_text).classes("pp-set-help")
            with ui.row().classes("pp-set-control items-center no-wrap"):
                label, act = ("Revoke", self._revoke) if grant else ("Allow", self._allow)
                ui.button(label, on_click=act, color=None).props("flat dense no-caps").classes(
                    "pp-mem-change"
                )
        if grant is None:
            return
        with ui.row().classes("pp-set-row items-center"):
            with ui.column().classes("pp-set-text"):
                ui.label("File types").classes("pp-set-label")
                ui.label("e.g. .md, .txt").classes("pp-set-help")
            with ui.row().classes("pp-set-control items-center no-wrap"):
                box = ui.input(value=", ".join(grant.file_types)).props("dense outlined")
                box.classes("pp-set-field")
                box.on("blur", lambda _e, b=box: self._set_types(str(b.value or "")))
                box.on("keydown.enter", lambda _e, b=box: self._set_types(str(b.value or "")))
        self._path_list(
            grant,
            "allow_paths",
            "Outside folders and notes",
            "Name a path in the chat to allow it" if not grant.allow_paths else "Allowed from chat",
            None,
        )
        self._path_list(
            grant, "exclude", "Never read", "Vault folders, notes or patterns", "private/"
        )

    def _path_list(
        self, grant: Grant, attr: str, label: str, help_text: str, hint: str | None
    ) -> None:
        """A list with × per item, and (with a ``hint``) a box to add one."""
        with ui.column().classes("pp-set-row pp-access-list"):
            with ui.row().classes("items-center no-wrap w-full"):
                with ui.column().classes("pp-set-text"):
                    ui.label(label).classes("pp-set-label")
                    ui.label(help_text).classes("pp-set-help")
                if hint is not None:  # outside paths are added from the chat (PLAN §4.26)
                    self._add_box(attr, hint)
            for item in getattr(grant, attr):
                with ui.row().classes("pp-access-item items-center no-wrap w-full"):
                    ui.label(item).classes("pp-set-help pp-access-path")
                    icon_button("x", lambda i=item: self._remove(attr, i), "Remove", size="m")

    def _add_box(self, attr: str, hint: str) -> None:
        with ui.row().classes("pp-set-control items-center no-wrap"):
            box = ui.input(placeholder=hint).props("dense outlined").classes("pp-set-field")
            error = ui.label("").classes("pp-set-error")
            error.set_visibility(False)

            def add(_e: object = None) -> None:
                self._add(attr, str(box.value or ""), error)

            box.on("keydown.enter", add)
            icon_button("plus", add, "Add", size="m")

    # ---- changes ---------------------------------------------------------------------------

    def _allow(self) -> None:
        self.ai.allow()
        self._rows.refresh()

    def _revoke(self) -> None:
        self.ai.revoke_access()
        self._rows.refresh()

    def _set_types(self, text: str) -> None:
        grant = self._grant()
        if grant is None:
            return
        types = parse_types(text)
        if types != grant.file_types:
            grant.file_types = types
            self._save(grant)

    def _add(self, attr: str, value: str, error: ui.label) -> None:
        grant = self._grant()
        if grant is None:
            return
        value = value.strip().strip("/")
        why = "" if value else "Type a vault path or pattern."
        if why:
            error.set_text(why)
            error.set_visibility(True)
            return
        setattr(grant, attr, unique([*getattr(grant, attr), value]))
        self._save(grant)

    def _remove(self, attr: str, item: str) -> None:
        grant = self._grant()
        if grant is None:
            return
        setattr(grant, attr, [i for i in getattr(grant, attr) if i != item])
        self._save(grant)
