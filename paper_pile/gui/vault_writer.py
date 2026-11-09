"""How the vault agent's changes reach the notes in the app (PLAN_vault_agent P30.31, PLAN
§4.32; ``core/ai/vault/edits.NoteWriter`` / ``ReviewWriter``): through the editor pane, so an
open tab shows the change at once, its buffer and autosave stay right, the index is updated
and the text before is kept in version history. A note whose text is not the one the diff was
made from is never written.

*Apply at once* comes through :meth:`EditorWriter.write_async` (one undo step in an open note,
the changed lines flash); *Review in the note* through :meth:`EditorWriter.review` (each note
opens with its diff, Accept / Reject there — no question in the chat).
"""

import logging
from typing import TYPE_CHECKING

from paper_pile.core.ai.proposals import propose
from paper_pile.core.ai.vault.edits import EditBatch, create_free
from paper_pile.core.vault import VaultError
from paper_pile.gui.components.memory_dialog import open_memory_dialog

if TYPE_CHECKING:
    from paper_pile.gui.components.editor_pane import EditorPane

log = logging.getLogger("paper_pile.gui.vault_writer")


class EditorWriter:
    def __init__(self, pane: "EditorPane") -> None:
        self.pane = pane

    def read(self, path: str) -> str:
        return self.pane.note_text(path)  # the open tab's buffer, else the file

    def write(self, path: str, before: str, after: str, reason: str) -> bool:
        """Undo of an AI change (and tools): the whole text, no flash."""
        try:
            if self.pane.note_text(path) != before:
                return False  # changed since the diff was made
            self.pane.keep_version(path, before, reason)
            self.pane.replace_note(path, after)
        except (VaultError, OSError):
            log.exception("could not write %s", path)
            return False
        return True

    async def write_async(self, path: str, before: str, after: str, reason: str) -> bool:
        """*Apply at once*: one undo step in an open note, its changed lines flash."""
        try:
            return await self.pane.write_ai(path, before, after, reason)
        except (VaultError, OSError):
            log.exception("could not write %s", path)
            return False

    def create(self, path: str, text: str) -> str | None:
        made = create_free(self.pane.vault, path, text)
        if made is not None and self.pane.index is not None:
            self.pane.index.update_note(made)
        return made

    async def review(self, batch: EditBatch) -> bool:
        """*Review in the note*: every changed note opens with its diff (the first one on
        screen); a new note is made empty and shows its whole text as the diff — rejected, it
        goes to the trash. Several notes: one tab each until the grouped AI changes tab
        (P31.5)."""
        shown = False
        for k, edit in enumerate(batch.ready):
            first = k == 0
            if edit.new:
                path = self.create(edit.path, "")
                proposal = propose(path, "", 0, 0, edit.after) if path else None
                if path is None or proposal is None:
                    continue
                shown |= await self.pane.show_ai_change(path, proposal, new=True, activate=first)
            elif edit.proposal is not None:
                shown |= await self.pane.show_ai_change(edit.path, edit.proposal, activate=first)
        return shown

    async def review_memory(self, before: str, after: str) -> bool:
        """The memory file's change for review: its editor opens with the change in it."""
        with self.pane.empty_host:
            open_memory_dialog(
                self.pane.vault.root, after, note="The AI's change is in it: save to keep it."
            )
        return True
