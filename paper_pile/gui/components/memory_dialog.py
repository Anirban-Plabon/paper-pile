"""The editor of the notes for the AI about a vault (``.paper-pile/ai.md``, PLAN_vault_agent
§5.6): opened from Settings → AI, and by the chat's "remember …" in *Review in the note* mode
with the AI's change already in it (PLAN §4.32) — the user saves or cancels there."""

from pathlib import Path

from nicegui import ui

from paper_pile.core.ai.vault.memory import MAX_CHARS, read_memory_file, save_memory
from paper_pile.gui.dialog import Dialog

TITLE = "Notes for the AI about this vault"


def open_memory_dialog(root: Path, text: str | None = None, *, note: str = "") -> None:
    """Open the editor (in the caller's slot) with ``text`` (default: the file's text). Save
    writes the file; the dialog is deleted when it closes. Returns at once."""
    with Dialog() as dialog, ui.card().classes("pp-dialog pp-instr-dialog"):
        ui.label(TITLE).classes("pp-dialog-title")
        if note:
            ui.label(note).classes("pp-muted")
        box = ui.textarea(
            value=read_memory_file(root) if text is None else text,
            placeholder="e.g.\n- Daily notes are in Journal/ as YYYY-MM-DD\n"
            "- One note per client in Clients/, each with a Budget section",
        ).props(f"outlined maxlength={MAX_CHARS * 2}")
        box.classes("pp-instr-big")
        ui.label(f"The first {MAX_CHARS} characters are sent. Saved in .paper-pile/ai.md.").classes(
            "pp-muted pp-instr-count"
        )

        def save() -> None:
            try:
                save_memory(root, str(box.value or ""))
                ui.notify("Saved", position="bottom", timeout=1500)
            except OSError as exc:
                ui.notify(f"Could not save: {exc}", type="warning", position="bottom")
            dialog.close()

        with ui.row().classes("items-center w-full no-wrap"):
            ui.space()
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            ui.button("Save", on_click=save).props("no-caps unelevated")
    dialog.on("hide", lambda: dialog.delete())
    dialog.open()
