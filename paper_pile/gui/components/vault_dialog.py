"""The "Open vault" dialog: recent vaults, and a folder browser for any other folder. The same
browser picks any folder (``ask_folder``: Settings → AI → Memories folder).

The browser lists the computer's folders from Python, so it works the same in the native window
and in ``--serve`` mode (a web page cannot see the server's folders). The native window also
has "Browse": the system's own folder picker.
"""

from pathlib import Path
from typing import Any

from nicegui import app, ui

from paper_pile.core.folders import is_vault, start_folder, subfolders
from paper_pile.core.session import load_recent_vaults
from paper_pile.gui.dialog import Dialog
from paper_pile.gui.icons import icon_button, line_icon
from paper_pile.gui.tips import tip


async def ask_vault(current: Path, *, native: bool) -> Path | None:
    """Ask which folder to open as the vault; ``None`` if cancelled."""
    recent = [v for v in load_recent_vaults() if v != current]
    return await ask_folder(start_folder(current), native=native, recent=recent)


async def ask_folder(
    start: Path,
    *,
    native: bool,
    title: str = "Open vault",
    action: str = "Open",
    recent: list[Path] | None = None,
) -> Path | None:
    """Ask for a folder, browsing from ``start``; ``None`` if cancelled."""
    recent = recent or []
    state: dict[str, Any] = {"folder": start}
    with Dialog() as dialog, ui.card().classes("pp-dialog pp-picker pp-vault-dialog"):
        ui.label(title).classes("pp-dialog-title")
        if recent:
            ui.label("Recent").classes("pp-vault-section")
            with ui.column().classes("pp-picker-list pp-vault-recent"):
                for i, vault in enumerate(recent):
                    with (
                        ui.row()
                        .classes("pp-picker-row items-center no-wrap")
                        .mark(f"recent-{i}") as row
                    ):
                        line_icon("folder-clock").classes("pp-picker-icon")
                        ui.label(vault.name or str(vault))
                        ui.label(str(vault.parent)).classes("pp-muted pp-vault-path")
                    row.on("click", lambda _e, v=vault: dialog.submit(v))
        ui.label("Folders").classes("pp-vault-section")
        with ui.row().classes("items-center no-wrap w-full pp-vault-bar"):
            up = icon_button("arrow-up", lambda: go(state["folder"].parent), "Up one folder")
            field = (
                ui.input().props("outlined dense").classes("pp-grow pp-vault-field").mark("path")
            )
        listing = ui.column().classes("pp-picker-list pp-vault-list")

        def go(folder: Path) -> None:
            folder = folder.expanduser()
            if not folder.is_dir():
                field.props('error error-message="No such folder"')
                return
            field.props(remove="error")
            state["folder"] = folder
            field.value = str(folder)
            up.set_enabled(folder.parent != folder)
            open_btn.set_text(f'{action} "{folder.name or folder}"')
            listing.clear()
            with listing:
                shown = subfolders(folder)
                if not shown:
                    ui.label("No folders inside").classes("pp-muted pp-vault-empty")
                for i, sub in enumerate(shown):
                    with (
                        ui.row()
                        .classes("pp-picker-row items-center no-wrap")
                        .mark(f"folder-{i}") as row
                    ):
                        line_icon("folder").classes("pp-picker-icon")
                        ui.label(sub.name)
                        if is_vault(sub):
                            ui.label("vault").classes("pp-picker-badge")
                    row.on("click", lambda _e, s=sub: go(s))

        async def system_picker() -> None:
            import webview  # native window only (the server process has pywebview installed)

            chosen = await app.native.main_window.create_file_dialog(  # type: ignore[union-attr]
                dialog_type=webview.FileDialog.FOLDER, directory=str(state["folder"])
            )
            picked = chosen if isinstance(chosen, str) else (chosen[0] if chosen else None)
            if picked:
                dialog.submit(Path(picked))

        field.on("keydown.enter", lambda _e: go(Path(str(field.value or "").strip() or "~")))
        with ui.row().classes("items-center no-wrap w-full"):
            if native:
                tip(
                    ui.button("Browse", on_click=system_picker).props("flat no-caps"),
                    "Choose the folder with the system's folder picker",
                )
            ui.space()
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
            open_btn = ui.button(on_click=lambda: dialog.submit(state["folder"])).props(
                "no-caps unelevated"
            )
        go(state["folder"])
    picked = await dialog
    dialog.delete()
    return picked if isinstance(picked, Path) else None
