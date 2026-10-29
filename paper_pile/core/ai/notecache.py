"""The vault's notes as the AI reads them: the list of paths and their text, cached (PLAN §4.26).

Building a message's context must not walk the vault or re-read unchanged notes (slow on WSL's
``/mnt/*``, and it runs on the UI's event loop). The path list is kept for a few seconds, or until
:meth:`NoteCache.invalidate` (a note was created, renamed or deleted); a note's text is kept
while its modification time and size stay the same, for the ``MAX_TEXTS`` notes read last.
"""

import time
from collections.abc import Callable

from paper_pile.core.vault import Vault, VaultError

PATHS_TTL_S = 5.0
MAX_TEXTS = 500  # texts kept (the least recently read go first)


class NoteCache:
    def __init__(self, vault: Vault, clock: Callable[[], float] = time.monotonic) -> None:
        self.vault = vault
        self._clock = clock
        self._paths: list[str] | None = None
        self._paths_at = 0.0
        self._texts: dict[str, tuple[int, int, str]] = {}  # path -> (mtime_ns, size, text)

    def paths(self) -> list[str]:
        """Every note path (as :meth:`Vault.walk_notes`), at most ``PATHS_TTL_S`` old."""
        now = self._clock()
        if self._paths is None or now - self._paths_at > PATHS_TTL_S:
            self._paths, self._paths_at = list(self.vault.walk_notes()), now
        return self._paths

    def read(self, path: str) -> str | None:
        """The note's text, or None when it cannot be read."""
        try:
            st = self.vault.resolve(path).stat()
        except (OSError, VaultError):
            self._texts.pop(path, None)
            return None
        kept = self._texts.pop(path, None)
        if kept is not None and kept[:2] == (st.st_mtime_ns, st.st_size):
            self._texts[path] = kept  # to the end: read last
            return kept[2]
        try:
            text = self.vault.read_text(path)
        except VaultError:
            return None
        self._texts[path] = (st.st_mtime_ns, st.st_size, text)
        while len(self._texts) > MAX_TEXTS:
            del self._texts[next(iter(self._texts))]
        return text

    def invalidate(self) -> None:
        """Notes were added, renamed or deleted: list them again next time."""
        self._paths = None
