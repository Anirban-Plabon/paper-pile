"""What the ⋯ note menu does (PLAN §4.15). The rules live in core (``core/merge.py``,
``core/export.py``, ``core/printdoc.py``, ``core/vault.py``); this module asks the user (pickers,
confirmations, a save dialog) and hands the results to the editor pane, the tree and the chat."""

import json
import logging
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from nicegui import app, ui

from paper_pile.core import assets
from paper_pile.core.export import export_html, export_markdown
from paper_pile.core.links import link_keys
from paper_pile.core.merge import plan_merge
from paper_pile.core.picker import search_notes
from paper_pile.core.titles import note_name
from paper_pile.core.vault import VaultError
from paper_pile.gui import printing
from paper_pile.gui.components.note_menu import NoteActions
from paper_pile.gui.dialog import Dialog
from paper_pile.gui.icons import close_button, line_icon
from paper_pile.gui.printing import build_print_page, paper_name
from paper_pile.gui.window import native_request

if TYPE_CHECKING:
    from paper_pile.gui.components.editor_pane import EditorPane

log = logging.getLogger("paper_pile.note_actions")

VAULT_ROOT = ""
SUMMARIZE = "Summarize this note in a few short bullet points."
REWRITE = (
    "Rewrite this note so it reads clearly and is well organised. Keep its meaning, its facts "
    "and its markdown formatting."
)
WRITE = "Write "


def note_actions(pane: "EditorPane", note: Callable[[], str | None] | None = None) -> NoteActions:
    """The actions on note ``note()`` (default: the one on screen; the tab menu passes its
    tab's note)."""
    current = note or pane.active_note

    def with_note(run: Any) -> Any:
        def action() -> Any:
            path = current()
            return run(path) if path is not None else None

        return action

    return NoteActions(
        find=lambda: pane.open_search(False),
        replace=lambda: pane.open_search(True),
        tidy=pane.tidy_active,
        toggle_split=pane.toggle_split,
        toggle_page_view=pane.toggle_page_view,
        outline=pane.show_outline,
        history=with_note(pane.show_history),
        pin=with_note(lambda p: pane.set_pinned(p, not pane.is_pinned(p))),
        move=with_note(lambda p: _move(pane, p)),
        merge=with_note(lambda p: _merge(pane, p)),
        add_to_chat=with_note(pane.add_to_chat),
        summarize=with_note(lambda p: _ask(pane, p, SUMMARIZE, send=True)),
        rewrite=with_note(lambda p: _ask(pane, p, REWRITE, send=True)),
        write=with_note(lambda p: pane.ask_chat(p, WRITE, False)),
        copy_path=with_note(lambda p: _copy(pane, p)),
        copy_full_path=with_note(lambda p: _copy(pane, str(pane.vault.resolve(p)))),
        export_markdown=with_note(lambda p: _export(pane, p, "md")),
        export_html=with_note(lambda p: _export(pane, p, "html")),
        export_pdf=with_note(lambda p: _export_pdf(pane, p)),
    )


async def _ask(pane: "EditorPane", path: str, prompt: str, *, send: bool) -> None:
    await pane.save_now()  # the chat reads the note from disk
    pane.ask_chat(path, prompt, send)


def _copy(pane: "EditorPane", text: str) -> None:
    with pane.host:
        ui.clipboard.write(text)
        ui.notify("Copied", timeout=1200, position="bottom")


# ---- move -----------------------------------------------------------------------------------


async def _move(pane: "EditorPane", path: str) -> None:
    here = PurePosixPath(path).parent.as_posix()
    here = VAULT_ROOT if here == "." else here
    options = {VAULT_ROOT: "Vault (top level)"} | {f: f for f in pane.vault.folders()}
    options.pop(here, None)
    if not options:
        pane.toast("There is no other folder to move it to.")
        return
    with pane.host, Dialog() as dialog, ui.card().classes("pp-dialog"):
        ui.label(f"Move “{note_name(path)}” to").classes("pp-dialog-title")
        where = (
            ui.select(options, value=next(iter(options)), label="Folder", with_input=True)
            .props("outlined dense autofocus")
            .classes("w-full")
        )
        with ui.row().classes("justify-end w-full"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
            ui.button("Move", on_click=lambda: dialog.submit(where.value)).props("no-caps")
    folder = await dialog
    dialog.delete()
    if folder is None:
        return
    await pane.save_now()
    pane.bus.publish("note.move", path=path, folder=str(folder))  # the tree moves it (tabs follow)


# ---- merge ----------------------------------------------------------------------------------


async def pick_split_note(pane: "EditorPane", title: str) -> str | None:
    """Which note to show in a side of the split: open tabs first, any note by search."""
    return await _pick_note(pane, title, first=pane.open_paths())


async def _pick_note(
    pane: "EditorPane", title: str, exclude: str = "", first: list[str] | None = None
) -> str | None:
    """A note picker. ``first`` (open tabs) leads the list until something is typed, each
    marked "Open"; typing searches every note."""
    notes = [n for n in pane.vault.walk_notes() if n != exclude]
    lead = [n for n in (first or []) if n in set(notes)]
    rest = sorted((n for n in notes if n not in set(lead)), key=str.lower)
    state: dict[str, Any] = {"query": "", "selected": 0, "shown": []}
    # the same look and place as the palette / quick switcher (picker_popup.py); the title is
    # the search box's placeholder
    with (
        pane.host,
        Dialog().props(
            "position=top transition-show=none transition-hide=none transition-duration=0"
        ) as dialog,
        ui.card().classes("pp-picker"),
    ):
        with ui.row().classes("pp-picker-head items-center no-wrap"):
            field = (
                ui.input(placeholder=title)
                .props("dense borderless autofocus")
                .classes("pp-picker-input")
            )
            close_button(lambda: dialog.submit(None), "Close (Esc)").classes("pp-picker-close")
        listing = ui.column().classes("pp-picker-list")

        def render() -> None:
            query = state["query"]
            shown = state["shown"] = search_notes(query, notes) if query.strip() else lead + rest
            state["selected"] = min(state["selected"], max(0, len(shown) - 1))
            listing.clear()
            with listing:
                if not shown:
                    ui.label("No notes found").classes("pp-muted")
                for i, note in enumerate(shown):
                    folder, _, name = note.rpartition("/")
                    row = ui.row().classes("pp-picker-row items-center no-wrap")
                    if i == state["selected"]:
                        row.classes("pp-picker-on")
                    with row:
                        line_icon("file-text").classes("pp-picker-icon")
                        ui.label(name.rsplit(".", 1)[0]).classes("pp-picker-title")
                        if folder:
                            ui.label(folder).classes("pp-picker-sub")
                        if note in lead:
                            ui.label("Open").classes("pp-picker-badge")
                    row.on("click", lambda _e, n=note: dialog.submit(n))

        def move(delta: int) -> None:
            if state["shown"]:
                state["selected"] = (state["selected"] + delta) % len(state["shown"])
                render()

        def changed(e: Any) -> None:
            state["query"], state["selected"] = str(e.value or ""), 0
            render()

        field.on_value_change(changed)
        field.on("keydown.down.prevent", lambda _e: move(1))
        field.on("keydown.up.prevent", lambda _e: move(-1))
        field.on(
            "keydown.enter.prevent",
            lambda _e: dialog.submit(state["shown"][state["selected"]]) if state["shown"] else None,
        )
        render()
    picked = await dialog
    dialog.delete()
    return None if picked is None else str(picked)


async def _confirm(pane: "EditorPane", title: str, detail: str, ok: str) -> bool:
    with pane.host, Dialog() as dialog, ui.card().classes("pp-dialog"):
        ui.label(title).classes("pp-dialog-title")
        ui.label(detail).classes("pp-muted pp-dialog-text")
        with ui.row().classes("justify-end w-full"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat no-caps")
            ui.button(ok, on_click=lambda: dialog.submit(True)).props("no-caps")
    result = await dialog
    dialog.delete()
    return bool(result)


async def _merge(pane: "EditorPane", source: str) -> None:
    target = await _pick_note(pane, f"Merge “{note_name(source)}” into…", exclude=source)
    if target is None:
        return
    detail = (
        f"Its text is added to the end of “{note_name(target)}”, its images move along and links "
        f"to it will point to “{note_name(target)}”. “{note_name(source)}” then goes to the trash."
    )
    if not await _confirm(pane, "Merge these notes?", detail, "Merge"):
        return
    if not await pane.save_now():
        pane.toast("Some notes could not be saved; nothing was merged.", error=True)
        return
    try:
        paths = list(pane.vault.walk_notes())
        others: dict[str, str] = {}
        if pane.index is not None:
            pane.index.sync()
            for path in pane.index.link_sources(link_keys([source])):
                others[path] = pane.note_text(path)
        plan = plan_merge(
            source, target, pane.note_text(source), pane.note_text(target), paths, others
        )
        pane.keep_version(target, pane.note_text(target), "before merge")
        assets.move_assets(pane.vault, source, target)
        pane.replace_note(target, plan.text)
        for path, text in plan.updated.items():
            pane.replace_note(path, text)
        pane.close_note(source)
        trashed = pane.vault.delete(source)
    except (VaultError, OSError) as exc:
        log.exception("merging %s into %s failed", source, target)
        pane.toast(f"Could not merge: {exc}", error=True)
        return
    pane.bus.publish("vault.deleted", path=source, trashed=trashed)
    pane.bus.publish("tree.open", path=target)
    pane.after_merge()
    message = f"Merged into “{note_name(target)}”"
    if plan.updated:
        message += f"; links updated in {len(plan.updated)} other note(s)"
    pane.toast(message)
    if plan.skipped:
        pane.toast(f"{plan.skipped} link(s) could not be updated automatically", error=True)


# ---- export ---------------------------------------------------------------------------------


async def _export(pane: "EditorPane", path: str, kind: str) -> None:
    await pane.save_now()
    try:
        text = pane.note_text(path)
        name = note_name(path)
        if kind == "md":
            content, filename = export_markdown(pane.vault, path, text), f"{name}.md"
        else:
            content, filename = export_html(pane.vault, path, text, name), f"{name}.html"
    except (VaultError, OSError) as exc:
        pane.toast(f"Could not export: {exc}", error=True)
        return
    if not pane.native:
        with pane.host:  # web mode: the browser saves it
            ui.download.content(content.encode("utf-8"), filename)
        return
    import webview  # native window only (the server process has pywebview installed)

    chosen = await app.native.main_window.create_file_dialog(  # type: ignore[union-attr]
        dialog_type=webview.FileDialog.SAVE, save_filename=filename
    )
    target = chosen if isinstance(chosen, str) else (chosen[0] if chosen else None)
    if not target:
        return
    try:
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    except OSError as exc:
        pane.toast(f"Could not write {target}: {exc}", error=True)
        return
    pane.toast(f"Exported to {target}")


# In web mode the page prints itself (`?mode=print`) from a frame the user never sees: the
# browser's print dialog shows the note's pages.
_PRINT_IN_FRAME = """(() => {
  const f = document.createElement('iframe');
  f.className = 'pp-print-frame';
  f.src = %s;
  document.body.appendChild(f);
  setTimeout(() => f.remove(), 600000);
})()"""


async def _export_pdf(pane: "EditorPane", path: str) -> None:
    """The note as a PDF with the pages page view shows (PLAN §4.17)."""
    await pane.save_now()
    name = note_name(path)
    try:
        html = build_print_page(pane.vault, pane.config, path, pane.note_text(path), name)
    except (VaultError, OSError) as exc:
        pane.toast(f"Could not export: {exc}", error=True)
        return
    url = printing.store(html)
    if not pane.native:
        with pane.host:
            ui.run_javascript(_PRINT_IN_FRAME % json.dumps(f"{url}?mode=print"))
        pane.toast("Choose “Save as PDF” in the print dialog")
        return
    import webview  # native window only (the server process has pywebview installed)

    chosen = await app.native.main_window.create_file_dialog(  # type: ignore[union-attr]
        dialog_type=webview.FileDialog.SAVE,
        save_filename=f"{name}.pdf",
        file_types=("PDF (*.pdf)",),
    )
    target = chosen if isinstance(chosen, str) else (chosen[0] if chosen else None)
    if not target:
        return
    if not target.lower().endswith(".pdf"):
        target += ".pdf"
    with pane.host:
        origin = await ui.run_javascript("location.origin")
    pane.toast("Exporting…")
    result = await native_request("print_pdf", f"{origin}{url}", target, paper_name(pane.config))
    if result == "ok":
        pane.toast(f"Exported to {target}")
    else:
        pane.toast("Could not export the PDF", error=True)
