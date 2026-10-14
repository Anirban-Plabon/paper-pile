"""The in-memory state of one open note, and the rules that keep its text from being lost.

A :class:`NoteBuffer` knows what is on disk (by hash) and what the editor holds. It is *dirty*
exactly when the two differ, so undoing back to the saved text clears the flag. Every dirty
state is mirrored to the recovery store; a successful save clears it. Saving never recreates
a note that vanished from disk (it reports a failure and keeps the text instead).

Timing (debounce, blur, tab switch) belongs to the UI; this module only decides *what* happens.
"""

import hashlib
import logging
from dataclasses import dataclass

from paper_pile.core.recovery import RecoveryEntry, RecoveryStore
from paper_pile.core.vault import NotFoundError, Vault, VaultError

log = logging.getLogger("paper_pile.buffer")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class NoteBuffer:
    vault: Vault
    recovery: RecoveryStore
    path: str
    text: str
    saved_hash: str | None  # None: the note does not exist on disk yet
    error: str | None = None  # why the last save failed

    @classmethod
    def open(
        cls, vault: Vault, recovery: RecoveryStore, path: str, *, recovered: str | None = None
    ) -> "NoteBuffer":
        """Load ``path``. With ``recovered``, the buffer starts as that unsaved text instead."""
        disk: str | None
        try:
            disk = vault.read_text(path)
        except NotFoundError:
            if recovered is None:
                raise
            disk = None  # restoring a note whose file is gone: saving will recreate it
        text = recovered if recovered is not None else disk
        assert text is not None  # disk is only None when recovered is given
        buf = cls(vault, recovery, path, text, None if disk is None else content_hash(disk))
        buf._mirror()
        return buf

    @property
    def dirty(self) -> bool:
        return content_hash(self.text) != self.saved_hash

    def set_text(self, text: str) -> None:
        if text == self.text:
            return
        self.text = text
        self._mirror()

    def save(self) -> bool:
        """Write the buffer to disk atomically. Returns False (text kept) on any failure."""
        if not self.dirty:
            self.error = None
            return True
        try:
            if self.vault.exists(self.path):
                self.vault.write_text(self.path, self.text)
            elif self.saved_hash is None:
                self.vault.create_note(self.path, self.text)
            else:
                self.error = "the note was deleted or moved on disk; your text is kept"
                return False
        except (VaultError, OSError) as exc:
            log.warning("saving %s failed: %s", self.path, exc)
            self.error = str(exc) or exc.__class__.__name__
            return False
        self.saved_hash = content_hash(self.text)
        self.error = None
        self.recovery.clear(self.path)
        return True

    def rename(self, new_path: str) -> None:
        """The note was renamed or moved; keep following it."""
        self.recovery.clear(self.path)
        self.path = new_path
        self._mirror()

    def discard(self) -> None:
        """Forget the buffer without saving (e.g. its note was deleted)."""
        self.recovery.clear(self.path)

    def _mirror(self) -> None:
        if self.dirty:
            self.recovery.write(self.path, self.text, self.saved_hash)
        else:
            self.recovery.clear(self.path)


def find_recoverable(vault: Vault, recovery: RecoveryStore) -> list[RecoveryEntry]:
    """Recovery entries worth offering. Entries that match what is on disk are dropped."""
    offer: list[RecoveryEntry] = []
    for entry in recovery.pending():
        try:
            if vault.read_text(entry.path) == entry.text:
                recovery.clear(entry.path)  # already saved; nothing to recover
                continue
        except NotFoundError:
            pass  # the note is gone but its unsaved text is not
        except VaultError:
            continue  # not a note we can handle (bad path/extension); leave the file alone
        offer.append(entry)
    return offer
