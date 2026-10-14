"""Crash safety: unsaved buffers are mirrored to ``<vault>/.paper-pile/recovery/``.

One small JSON file per note, written whenever a buffer has changes that are not on disk yet
and removed as soon as the note is saved (or the buffer returns to its saved content). After
a crash or a failed save, whatever is left in this folder is offered back to the user.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from paper_pile.core.fsutil import atomic_write_bytes

log = logging.getLogger("paper_pile.recovery")

META_DIR = ".paper-pile"
RECOVERY_DIR = "recovery"


@dataclass(frozen=True, slots=True)
class RecoveryEntry:
    path: str  # vault-relative, POSIX
    text: str  # the unsaved buffer
    base_hash: str | None  # hash of the note's saved content when the buffer diverged
    saved_at: float  # unix time of the last mirror


class RecoveryStore:
    def __init__(self, vault_root: Path) -> None:
        self.dir = vault_root / META_DIR / RECOVERY_DIR

    def _file(self, path: str) -> Path:
        return self.dir / (hashlib.sha256(path.encode("utf-8")).hexdigest()[:20] + ".json")

    def write(self, path: str, text: str, base_hash: str | None) -> None:
        """Mirror an unsaved buffer. Never raises: recovery is a safety net, not a gate."""
        payload = {"path": path, "text": text, "base_hash": base_hash, "saved_at": time.time()}
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(self._file(path), json.dumps(payload).encode("utf-8"))
        except OSError:
            log.warning("could not mirror %s to the recovery folder", path, exc_info=True)

    def clear(self, path: str) -> None:
        self._file(path).unlink(missing_ok=True)

    def get(self, path: str) -> RecoveryEntry | None:
        return self._read(self._file(path))

    def pending(self) -> list[RecoveryEntry]:
        """Every readable entry, oldest first. Unreadable files are skipped (and left alone)."""
        if not self.dir.is_dir():
            return []
        entries = [e for f in self.dir.glob("*.json") if (e := self._read(f)) is not None]
        return sorted(entries, key=lambda e: e.saved_at)

    @staticmethod
    def _read(file: Path) -> RecoveryEntry | None:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            base = data["base_hash"]
            if not isinstance(base, str | None):
                return None
            return RecoveryEntry(
                str(data["path"]), str(data["text"]), base, float(data["saved_at"])
            )
        except (FileNotFoundError, KeyError, TypeError, ValueError, OSError):
            return None
