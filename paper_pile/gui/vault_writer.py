"""How the vault agent's edits across notes reach the notes in the app (PLAN_vault_agent
P30.31, ``core/ai/vault/edits.NoteWriter``): through the editor pane, so an open tab shows
the change at once, its buffer and autosave stay right, the index is updated and the text
before is kept in version history. A note whose text is not the one the diff was made from
is never written.
"""

import logging
from typing import TYPE_CHECKING

from paper_pile.core.ai.vault.edits import create_free
from paper_pile.core.vault import VaultError

if TYPE_CHECKING:
    from paper_pile.gui.components.editor_pane import EditorPane

log = logging.getLogger("paper_pile.gui.vault_writer")


class EditorWriter:
    def __init__(self, pane: "EditorPane") -> None:
        self.pane = pane

    def read(self, path: str) -> str:
        return self.pane.note_text(path)  # the open tab's buffer, else the file

    def write(self, path: str, before: str, after: str, reason: str) -> bool:
        try:
            if self.pane.note_text(path) != before:
                return False  # changed since the diff was made
            self.pane.keep_version(path, before, reason)
            self.pane.replace_note(path, after)
        except (VaultError, OSError):
            log.exception("could not write %s", path)
            return False
        return True

    def create(self, path: str, text: str) -> str | None:
        made = create_free(self.pane.vault, path, text)
        if made is not None and self.pane.index is not None:
            self.pane.index.update_note(made)
        return made
