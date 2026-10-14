"""The vault: a folder of ``.md`` / ``.txt`` notes. All file operations live here.

Rules this module enforces (callers pass vault-relative POSIX paths):
  * Only the visible area is reachable: any path component starting with ``.`` (``.paper-pile``,
    ``.trash``, ``.<stem>.assets``) is refused, as is anything resolving outside the vault.
  * Writes are atomic; nothing is ever overwritten implicitly (create/rename/duplicate fail
    if the target exists); deletes move to ``<vault>/.trash/``, never unlink.
  * Asset folders and link rewriting are layered on top by ``assets.py`` / ``links.py``.
"""

import logging
import os
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from paper_pile.core.fsutil import atomic_write_bytes

log = logging.getLogger("paper_pile.vault")

META_DIR = ".paper-pile"
TRASH_DIR = ".trash"
NOTE_SUFFIXES = frozenset({".md", ".txt"})


class VaultError(Exception):
    """A vault operation was refused or failed."""


class InvalidPathError(VaultError):
    """The path is absolute, escapes the vault, is hidden, or has a bad extension."""


class NotFoundError(VaultError):
    """The path does not exist."""


class ExistsError(VaultError):
    """The target already exists (vault operations never overwrite)."""


def resolve_vault_path(raw: str | Path) -> Path:
    """Expand ``~``, make absolute, and require an existing directory."""
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise VaultError(f"vault directory does not exist: {path}")
    if not path.is_dir():
        raise VaultError(f"vault path is not a directory: {path}")
    return path


def ensure_vault_dir(root: Path) -> Path:
    """Create ``<vault>/.paper-pile/`` on first open and return it."""
    meta = root / META_DIR
    if not meta.exists():
        log.info("initialising vault metadata in %s", meta)
    meta.mkdir(exist_ok=True)
    return meta


def is_note_name(name: str) -> bool:
    return Path(name).suffix.lower() in NOTE_SUFFIXES


@dataclass(frozen=True, slots=True)
class TreeEntry:
    name: str
    path: str  # vault-relative, POSIX
    is_dir: bool


class Vault:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    # ---- paths ---------------------------------------------------------------------------

    def resolve(self, rel: str | PurePosixPath, *, allow_root: bool = False) -> Path:
        """Map a vault-relative path to an absolute one, refusing anything unsafe."""
        text = str(rel)
        pure = PurePosixPath(text)
        if pure.is_absolute() or "\\" in text or "\0" in text:
            raise InvalidPathError(f"not a vault-relative path: {text!r}")
        parts = [p for p in pure.parts if p != "."]
        if any(p == ".." for p in parts):
            raise InvalidPathError(f"path escapes the vault: {text!r}")
        if any(p.startswith(".") for p in parts):
            raise InvalidPathError(f"hidden paths are not accessible: {text!r}")
        if not parts and not allow_root:
            raise InvalidPathError("empty path")
        path = self.root.joinpath(*parts)
        if not self._inside(path):
            raise InvalidPathError(f"path resolves outside the vault: {text!r}")
        return path

    def _inside(self, path: Path) -> bool:
        return path.resolve().is_relative_to(self.root)

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _note_path(self, rel: str | PurePosixPath) -> Path:
        path = self.resolve(rel)
        if not is_note_name(path.name):
            raise InvalidPathError(f"not a note (.md/.txt): {rel!r}")
        return path

    # ---- reading -------------------------------------------------------------------------

    def list_tree(self, rel: str | PurePosixPath = "") -> list[TreeEntry]:
        """One level of ``rel``: folders first, then notes, each sorted case-insensitively.

        Hides dot entries, non-note files, and symlinks that point outside the vault.
        """
        folder = self.resolve(rel, allow_root=True)
        if not folder.is_dir():
            raise NotFoundError(f"not a folder: {rel!r}")
        entries: list[TreeEntry] = []
        with os.scandir(folder) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                path = Path(e.path)
                if e.is_symlink() and not self._inside(path):
                    continue
                is_dir = e.is_dir()
                if is_dir or (e.is_file() and is_note_name(e.name)):
                    entries.append(TreeEntry(e.name, self._rel(path), is_dir))
        entries.sort(key=lambda t: (not t.is_dir, t.name.lower(), t.name))
        return entries

    def walk_notes(self) -> Iterator[str]:
        """Every note path in the vault (for the indexer), skipping hidden folders."""
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if name.startswith(".") or not is_note_name(name):
                    continue
                if path.is_symlink() and not self._inside(path):
                    continue
                yield self._rel(path)

    def read_text(self, rel: str | PurePosixPath) -> str:
        path = self._note_path(rel)
        try:
            # newline="" keeps CRLF exactly as stored, so a round trip never rewrites endings
            with path.open(encoding="utf-8", newline="") as f:
                return f.read()
        except (FileNotFoundError, IsADirectoryError) as exc:
            raise NotFoundError(f"no such note: {rel!r}") from exc
        except UnicodeDecodeError as exc:
            raise VaultError(f"not valid UTF-8: {rel!r}") from exc

    # ---- writing -------------------------------------------------------------------------

    def write_text(self, rel: str | PurePosixPath, text: str) -> None:
        """Atomically replace (or create) a note inside an existing folder."""
        path = self._note_path(rel)
        if not path.parent.is_dir():
            raise NotFoundError(f"folder does not exist: {self._rel(path.parent)!r}")
        if path.is_dir():
            raise InvalidPathError(f"is a folder: {rel!r}")
        atomic_write_bytes(path, text.encode("utf-8"))

    def create_note(self, rel: str | PurePosixPath, text: str = "") -> str:
        """Create a new note (and missing parent folders). Fails if it already exists."""
        path = self._note_path(rel)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except (FileExistsError, NotADirectoryError) as exc:
            raise InvalidPathError(f"a parent of {rel!r} is a file") from exc
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError as exc:
            raise ExistsError(f"already exists: {rel!r}") from exc
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        return self._rel(path)

    def create_folder(self, rel: str | PurePosixPath) -> str:
        path = self.resolve(rel)
        try:
            path.mkdir(parents=True)
        except FileExistsError as exc:
            raise ExistsError(f"already exists: {rel!r}") from exc
        return self._rel(path)

    # ---- moving --------------------------------------------------------------------------

    def rename(self, src: str | PurePosixPath, dst: str | PurePosixPath) -> str:
        """Rename or move a note or folder. Never overwrites. Returns the new path."""
        s = self.resolve(src)
        if not s.exists():
            raise NotFoundError(f"no such path: {src!r}")
        d = self._note_path(dst) if s.is_file() else self.resolve(dst)
        if d.exists():
            raise ExistsError(f"already exists: {dst!r}")
        if not d.parent.is_dir():
            raise NotFoundError(f"folder does not exist: {self._rel(d.parent)!r}")
        if s.is_dir() and d.resolve().is_relative_to(s.resolve()):
            raise InvalidPathError("cannot move a folder into itself")
        s.rename(d)
        return self._rel(d)

    def duplicate(self, rel: str | PurePosixPath) -> str:
        """Copy a note or folder next to itself as ``<name> copy[ N]``. Returns the copy's path."""
        src = self.resolve(rel)
        if not src.exists():
            raise NotFoundError(f"no such path: {rel!r}")
        dst = _free_copy_name(src)
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
        return self._rel(dst)

    def delete(self, rel: str | PurePosixPath) -> str:
        """Move a note or folder to ``.trash/<timestamp>/<original path>``. Returns that path."""
        src = self.resolve(rel)
        if not src.exists() and not src.is_symlink():
            raise NotFoundError(f"no such path: {rel!r}")
        relpath = self._rel(src)
        stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
        dst = self.root / TRASH_DIR / stamp / relpath
        while dst.exists():  # same-microsecond collision: effectively never, but never overwrite
            dst = dst.with_name(dst.name + "_")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return self._rel(dst)


def _free_copy_name(src: Path) -> Path:
    stem, suffix = (src.name, "") if src.is_dir() else (src.stem, src.suffix)
    candidate = src.with_name(f"{stem} copy{suffix}")
    n = 2
    while candidate.exists():
        candidate = src.with_name(f"{stem} copy {n}{suffix}")
        n += 1
    return candidate
