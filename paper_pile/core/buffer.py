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
from enum import Enum

from paper_pile.core.recovery import RecoveryEntry, RecoveryStore
from paper_pile.core.vault import NotFoundError, Vault, VaultError

log = logging.getLogger("paper_pile.buffer")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Outcome(Enum):
    """What :meth:`NoteBuffer.sync_with_disk` found and did."""

    UNCHANGED = "unchanged"  # disk matches what we last saved/loaded (also our own save's echo)
    RELOADED = "reloaded"  # clean buffer: took the outside change silently
    CONFLICT = "conflict"  # unsaved edits here AND a different version on disk
    GONE = "gone"  # clean buffer, the note was deleted/moved away
    CONFLICT_GONE = "conflict_gone"  # unsaved edits here, the note was deleted/moved away


@dataclass(frozen=True, slots=True)
class DiskVersion:
    """The version of the note that appeared on disk behind our back (``text`` None = deleted)."""

    text: str | None


@dataclass
class NoteBuffer:
    vault: Vault
    recovery: RecoveryStore
    path: str
    text: str
    saved_hash: str | None  # None: the note does not exist on disk yet
    error: str | None = None  # why the last save failed
    conflict: DiskVersion | None = None  # set while an outside change waits for a decision

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
        if buf.dirty:
            buf._mirror()
        # A clean buffer must NOT clear the store: an older unsaved draft of this note may be
        # waiting there for the user to restore or discard it.
        return buf

    @property
    def dirty(self) -> bool:
        return content_hash(self.text) != self.saved_hash

    def set_text(self, text: str) -> None:
        if text == self.text:
            return
        self.text = text
        self._mirror()

    def sync_with_disk(self) -> Outcome:
        """Compare the note on disk with what we last saved or loaded and react.

        The comparison is by content hash, so the echo of our own save (the watcher reports it
        too) is simply "unchanged", and so is a `touch`. A clean buffer takes an outside change
        silently. A dirty one is never overwritten and never overwrites: it records a conflict
        and refuses to save until the user picks a side (:meth:`keep_mine` / :meth:`load_theirs`).
        """
        try:
            disk: str | None = self.vault.read_text(self.path)
        except NotFoundError:
            disk = None
        except VaultError:  # e.g. not valid UTF-8 now: leave the buffer alone
            log.warning("cannot read %s to compare with the buffer", self.path)
            return Outcome.UNCHANGED
        if disk is None:
            if self.saved_hash is None:
                return Outcome.UNCHANGED  # a restored draft of a note that never existed on disk
            if not self.dirty:
                return Outcome.GONE
            self.conflict = DiskVersion(None)
            return Outcome.CONFLICT_GONE
        disk_hash = content_hash(disk)
        if disk_hash == self.saved_hash:
            self.conflict = None  # the disk went back to what we know: nothing to decide
            return Outcome.UNCHANGED
        if not self.dirty:
            self.text, self.saved_hash, self.conflict = disk, disk_hash, None
            self.error = None  # a failed save of text we no longer hold is no longer relevant
            self.recovery.clear(self.path)
            return Outcome.RELOADED
        if content_hash(self.text) == disk_hash:  # someone wrote exactly what we have typed
            self.saved_hash, self.conflict, self.error = disk_hash, None, None
            self.recovery.clear(self.path)
            return Outcome.UNCHANGED
        self.conflict = DiskVersion(disk)
        return Outcome.CONFLICT

    def keep_mine(self) -> None:
        """Resolve a conflict in favour of this buffer: its next save overwrites the disk version
        (or recreates the note if it was deleted). The caller stashes the other side first."""
        if self.conflict is None:
            return
        self.saved_hash = None if self.conflict.text is None else content_hash(self.conflict.text)
        self.conflict = None
        self.error = None  # the user decided; the next save reports its own result
        self._mirror()

    def load_theirs(self) -> None:
        """Resolve a conflict in favour of the disk version; the unsaved edits are dropped (the
        caller stashes them first). Not meaningful for a deleted note."""
        if self.conflict is None or self.conflict.text is None:
            return
        self.text = self.conflict.text
        self.saved_hash = content_hash(self.text)
        self.conflict = None
        self.error = None
        self.recovery.clear(self.path)

    def save(self) -> bool:
        """Write the buffer to disk atomically. Returns False (text kept) on any failure."""
        if self.conflict is not None:
            self.error = "changed on disk: choose Keep mine or Load theirs first"
            return False
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
