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
import posixpath
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from paper_pile.core.fsutil import atomic_write_bytes

log = logging.getLogger("paper_pile.vault")

META_DIR = ".paper-pile"
TRASH_DIR = ".trash"
NOTE_SUFFIXES = frozenset({".md", ".txt"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"})
_ASSET_DIR = re.compile(r"^\..+\.assets$")  # `.<note stem>.assets`, the only hidden folders served
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


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


def is_plain_text(name: str) -> bool:
    """``.txt`` notes are plain text: no markdown rendering, no slash menu (PLAN §4.5)."""
    return Path(name).suffix.lower() == ".txt"


MAX_NAME_LEN = 255


def validate_name(name: str) -> str:
    """A single file or folder name typed by a user: no separators, not hidden, not empty."""
    name = name.strip()
    if not name:
        raise InvalidPathError("name is empty")
    if name in {".", ".."}:
        raise InvalidPathError(f"invalid name: {name!r}")
    if "/" in name or "\\" in name or "\0" in name:
        raise InvalidPathError("a name cannot contain / or \\")
    if name.startswith("."):
        raise InvalidPathError("a name cannot start with a dot")
    if len(name.encode("utf-8")) > MAX_NAME_LEN:
        raise InvalidPathError("name is too long")
    return name


def note_filename(name: str) -> str:
    """Validated note file name; ``.md`` is appended unless it already ends in .md/.txt."""
    name = validate_name(name)
    return name if is_note_name(name) else f"{name}.md"


def join_rel(folder: str | PurePosixPath, name: str) -> str:
    """Vault-relative POSIX path of ``name`` inside ``folder`` (``""`` is the vault root)."""
    return (PurePosixPath(str(folder)) / name).as_posix() if str(folder) not in {"", "."} else name


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

    def stash_text(self, rel: str | PurePosixPath, text: str, label: str) -> str:
        """Keep a version of a note that is about to be overwritten or dropped.

        Written to ``.trash/<stamp>/<folder>/<stem> (<label>)<ext>``; returns that path. Used when
        an outside edit and unsaved edits collide: whichever side loses is stashed here, so
        resolving a conflict never destroys text.
        """
        target = self.resolve(rel)  # also validates the path
        stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
        folder = PurePosixPath(str(rel)).parent
        name = f"{target.stem} ({label}){target.suffix}"
        dst = self.root / TRASH_DIR / stamp / ("" if str(folder) == "." else str(folder)) / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(dst, text.encode("utf-8"))
        return self._rel(dst)

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

    def exists(self, rel: str | PurePosixPath) -> bool:
        """True if ``rel`` is an existing note or folder inside the visible vault."""
        try:
            return self.resolve(rel).exists()
        except InvalidPathError:
            return False

    def asset_path(self, note: str | PurePosixPath, ref: str) -> Path:
        """Absolute path of the image ``ref`` as written in ``note`` (read access only).

        ``ref`` is the markdown URL, relative to the note's folder (``.mamba.assets/a3f9.png``,
        ``../pics/x.png``), possibly percent-encoded. Unlike every other Vault method this may
        enter hidden ``.<stem>.assets`` folders (that is where images live), and nothing else
        hidden: ``.trash``, ``.paper-pile`` and the like stay refused. Only image files, only
        inside the vault, no symlink escapes. Raises ``VaultError`` otherwise.
        """
        self.resolve(note)  # the note itself must be a safe vault path (it may not exist yet)
        ref = unquote(ref)
        if not ref or "\\" in ref or "\0" in ref or ref.startswith("/") or _SCHEME.match(ref):
            raise InvalidPathError(f"not a vault-relative image path: {ref!r}")
        folder = PurePosixPath(str(note)).parent.as_posix()
        joined = posixpath.normpath(posixpath.join("" if folder == "." else folder, ref))
        if joined in {"", "."} or joined == ".." or joined.startswith("../"):
            raise InvalidPathError(f"image path escapes the vault: {ref!r}")
        parts = PurePosixPath(joined).parts
        for part in parts[:-1]:
            if part.startswith(".") and not _ASSET_DIR.match(part):
                raise InvalidPathError(f"hidden folder is not accessible: {part!r}")
        name = parts[-1]
        if name.startswith(".") or PurePosixPath(name).suffix.lower() not in IMAGE_SUFFIXES:
            raise InvalidPathError(f"not an image: {name!r}")
        path = self.root.joinpath(*parts)
        if not self._inside(path):
            raise InvalidPathError(f"image resolves outside the vault: {ref!r}")
        if not path.is_file():
            raise NotFoundError(f"no such image: {ref!r}")
        return path

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

    def create_note_in(self, folder: str | PurePosixPath, name: str, text: str = "") -> str:
        """Create a note called ``name`` (``.md`` added if needed) inside ``folder``."""
        return self.create_note(join_rel(folder, note_filename(name)), text)

    def create_folder_in(self, folder: str | PurePosixPath, name: str) -> str:
        return self.create_folder(join_rel(folder, validate_name(name)))

    # ---- moving --------------------------------------------------------------------------

    def rename_in_place(self, rel: str | PurePosixPath, new_name: str) -> str:
        """Rename within the same folder. A note keeps its extension unless one is typed."""
        src = self.resolve(rel)
        if src.is_file():
            suffix = src.suffix
            new_name = validate_name(new_name)
            if not is_note_name(new_name):
                new_name += suffix
        else:
            new_name = validate_name(new_name)
        parent = PurePosixPath(str(rel)).parent
        target = join_rel(parent, new_name)
        if target == PurePosixPath(str(rel)).as_posix():
            return target
        return self.rename(rel, target)

    def move_into(self, rel: str | PurePosixPath, folder: str | PurePosixPath) -> str:
        """Move a note or folder into ``folder`` (``""`` = vault root). Same place is a no-op."""
        name = PurePosixPath(str(rel)).name
        target = join_rel(folder, name)
        if target == PurePosixPath(str(rel)).as_posix():
            return target
        if str(folder) not in {"", "."} and not self.resolve(folder).is_dir():
            raise NotFoundError(f"not a folder: {folder!r}")
        return self.rename(rel, target)

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
        was_note, old_rel = s.is_file(), self._rel(s)
        s.rename(d)
        if was_note:
            from paper_pile.core import assets

            assets.move_assets(self, old_rel, self._rel(d))
        return self._rel(d)

    def duplicate(self, rel: str | PurePosixPath) -> str:
        """Copy a note or folder next to itself as ``<name> copy[ N]``. Returns the copy's path.
        A note's images go with it (its own copy of the assets folder)."""
        src = self.resolve(rel)
        if not src.exists():
            raise NotFoundError(f"no such path: {rel!r}")
        dst = _free_copy_name(src)
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
            from paper_pile.core import assets

            assets.duplicate_assets(self, self._rel(src), self._rel(dst))
        return self._rel(dst)

    def trash_move(self, src: Path, relpath: str, stamp: str | None = None) -> str:
        """Move ``src`` to ``.trash/<stamp>/<relpath>`` (nothing is ever unlinked); returns the
        vault-relative trash path. Callers moving several things at once share one ``stamp``."""
        stamp = stamp or datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
        dst = self.root / TRASH_DIR / stamp / relpath
        while dst.exists():  # same-microsecond collision: effectively never, but never overwrite
            dst = dst.with_name(dst.name + "_")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return self._rel(dst)

    def delete(self, rel: str | PurePosixPath) -> str:
        """Move a note or folder to ``.trash/<timestamp>/<original path>``. Returns that path.
        A note's images go to the trash with it."""
        src = self.resolve(rel)
        if not src.exists() and not src.is_symlink():
            raise NotFoundError(f"no such path: {rel!r}")
        relpath = self._rel(src)
        stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
        is_note = src.is_file()
        trashed = self.trash_move(src, relpath, stamp)
        if is_note:
            from paper_pile.core import assets

            assets.trash_assets(self, relpath, stamp)
        return trashed


def _free_copy_name(src: Path) -> Path:
    stem, suffix = (src.name, "") if src.is_dir() else (src.stem, src.suffix)
    candidate = src.with_name(f"{stem} copy{suffix}")
    n = 2
    while candidate.exists():
        candidate = src.with_name(f"{stem} copy {n}{suffix}")
        n += 1
    return candidate
