"""What is in the vault's trash, and putting it back (PLAN §4.18). No UI here.

``Vault.delete`` moves a note or folder to ``.trash/<stamp>/<original path>`` (a note's images to
the same stamp folder) and writes ``.trash/<stamp>/.trash.json`` saying what was deleted:
``.trash/<stamp>/a/b.md`` alone cannot tell a deleted note ``a/b.md`` from a deleted folder
``a``. Stamp folders without that file (older deletes, the conflict copies of
``Vault.stash_text``) list each note in them separately.

Nothing is ever removed for good: restoring moves the item back (to a free name such as
``Note (restored).md`` if its old place is taken), then drops the emptied stamp folder.
"""

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from paper_pile.core.fsutil import atomic_write_bytes
from paper_pile.core.vault import (
    TRASH_DIR,
    NotFoundError,
    Vault,
    is_hidden_part,
    is_note_name,
    join_rel,
)

log = logging.getLogger("paper_pile.trash")

MANIFEST = ".trash.json"
_STAMP = "%Y-%m-%dT%H-%M-%S-%f"


@dataclass(frozen=True, slots=True)
class TrashItem:
    stamp: str  # the folder under .trash/
    path: str  # where it was in the vault (vault-relative POSIX)
    is_dir: bool
    deleted: datetime | None  # from the stamp; None if the stamp is not a time

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name


def write_manifest(vault: Vault, stamp: str, path: str, *, is_dir: bool) -> None:
    """Record what ``Vault.delete`` put in ``.trash/<stamp>/``."""
    data = {"path": path, "dir": is_dir}
    try:
        atomic_write_bytes(vault.root / TRASH_DIR / stamp / MANIFEST, json.dumps(data).encode())
    except OSError:
        log.warning("could not describe trash entry %s", stamp, exc_info=True)


def _deleted_at(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp, _STAMP)
    except ValueError:
        return None


def _manifest(folder: Path) -> tuple[str, bool] | None:
    try:
        data = json.loads((folder / MANIFEST).read_text())
    except (OSError, ValueError):
        return None
    path = data.get("path") if isinstance(data, dict) else None
    if not isinstance(path, str) or not path or not (folder / path).exists():
        return None
    return path, bool(data.get("dir"))


def list_trash(vault: Vault) -> list[TrashItem]:
    """Everything that can be restored, newest first."""
    trash = vault.root / TRASH_DIR
    if not trash.is_dir():
        return []
    items: list[TrashItem] = []
    for folder in sorted((p for p in trash.iterdir() if p.is_dir()), reverse=True):
        when = _deleted_at(folder.name)
        described = _manifest(folder)
        if described is not None:
            items.append(TrashItem(folder.name, described[0], described[1], when))
            continue
        for note in sorted(folder.rglob("*")):  # older entries: each note on its own
            rel = note.relative_to(folder)
            hidden = any(is_hidden_part(part, depth) for depth, part in enumerate(rel.parts))
            if note.is_file() and is_note_name(note.name) and not hidden:
                items.append(TrashItem(folder.name, rel.as_posix(), False, when))
    return items


def _free_target(vault: Vault, path: str, is_dir: bool) -> str:
    """``path`` if nothing is there, else ``<name> (restored)``, ``(restored 2)``, ..."""
    if not vault.resolve(path).exists():
        return path
    pure = PurePosixPath(path)
    stem, suffix = (pure.name, "") if is_dir else (pure.stem, pure.suffix)
    n = 1
    while True:
        label = "restored" if n == 1 else f"restored {n}"
        candidate = join_rel(pure.parent.as_posix(), f"{stem} ({label}){suffix}")
        if not vault.resolve(candidate).exists():
            return candidate
        n += 1


def restore(vault: Vault, item: TrashItem) -> str:
    """Put ``item`` back in the vault; returns where it went (its old path if that is free)."""
    from paper_pile.core import assets
    from paper_pile.core.rewrite import apply_edits

    folder = vault.root / TRASH_DIR / item.stamp
    src = folder / item.path
    if not src.exists():
        raise NotFoundError(f"not in the trash any more: {item.path!r}")
    target = _free_target(vault, item.path, item.is_dir)
    dst = vault.resolve(target)  # also validates the path
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dst)
    if not item.is_dir:
        images = folder / assets.assets_folder(item.path)
        if images.is_dir():
            new_images = vault.root / assets.assets_folder(target)
            new_images.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(images, new_images)
            if target != item.path:  # a new name: its image links name the new folder
                text = vault.read_text(target)
                edits = assets.plan_ref_edits(text, item.path, target)
                if edits:
                    vault.write_text(target, apply_edits(text, edits))
    _drop_if_empty(folder)
    return target


def _drop_if_empty(folder: Path) -> None:
    """Remove the stamp folder once only empty folders (and our description of it) are left."""
    leftovers = [p for p in folder.rglob("*") if p.is_file() and p.name != MANIFEST]
    if leftovers:
        return
    (folder / MANIFEST).unlink(missing_ok=True)
    for sub in sorted((p for p in folder.rglob("*") if p.is_dir()), reverse=True):
        sub.rmdir()
    folder.rmdir()
