"""Every image in a vault, for the gallery (PLAN §6 P13.7): where, how big, when, used by whom.

Images are the files in the images folder (``vault.images_folder``) and in the per-note
``.<stem>.assets`` folders. "Used by" comes from the image references of every note.
"""

import logging
import os
import posixpath
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from paper_pile.core.assets import image_size
from paper_pile.core.parser import image_spans
from paper_pile.core.vault import IMAGE_SUFFIXES, Vault, VaultError, is_hidden_part

log = logging.getLogger("paper_pile.gallery")

HEADER_BYTES = 64 * 1024  # enough to read the size of any image we accept


@dataclass(slots=True)
class ImageInfo:
    path: str  # vault-relative
    bytes: int
    modified: float
    width: int | None = None
    height: int | None = None
    used_by: list[str] = field(default_factory=list)  # notes that show it

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    @property
    def day(self) -> date:
        return datetime.fromtimestamp(self.modified).date()


def _is_asset_dir(name: str) -> bool:
    return name.startswith(".") and name.endswith(".assets") and len(name) > len("..assets")


def list_images(vault: Vault, images_folder: str) -> list[ImageInfo]:
    """The images of the vault, newest first (``used_by`` filled from every note)."""
    root, media = vault.root, images_folder.strip("/")
    found: dict[str, ImageInfo] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        depth = len(rel_dir.parts)
        dirnames[:] = [d for d in dirnames if not is_hidden_part(d, depth) or _is_asset_dir(d)]
        here = rel_dir.as_posix()
        in_media = bool(media) and (here == media or here.startswith(media + "/"))
        in_assets = any(_is_asset_dir(p) for p in rel_dir.parts)
        if not (in_media or in_assets):
            continue
        for name in filenames:
            if name.startswith(".") or PurePosixPath(name).suffix.lower() not in IMAGE_SUFFIXES:
                continue
            found[f"{here}/{name}" if here != "." else name] = _info(root, here, name)
    users = image_users(vault, vault.walk_notes())
    for path, info in found.items():
        info.used_by = sorted(users.get(path, ()), key=str.lower)
    return sorted(found.values(), key=lambda i: (-i.modified, i.path))


def _info(root: Path, folder: str, name: str) -> ImageInfo:
    path = root / folder / name
    rel = f"{folder}/{name}" if folder != "." else name
    stat = path.stat()
    info = ImageInfo(rel, stat.st_size, stat.st_mtime)
    try:
        with path.open("rb") as f:
            size = image_size(f.read(HEADER_BYTES))
    except OSError:
        size = None
    if size:
        info.width, info.height = size
    return info


def image_users(vault: Vault, notes: Iterable[str]) -> dict[str, set[str]]:
    """Vault-relative image path -> the notes whose text shows it."""
    users: dict[str, set[str]] = {}
    for note in notes:
        if not note.lower().endswith(".md"):
            continue
        try:
            text = vault.read_text(note)
        except VaultError:
            continue
        folder = PurePosixPath(note).parent.as_posix()
        for span in image_spans(text):
            raw = unquote(span.raw)
            if not raw or raw.startswith("/") or ":" in raw.split("/")[0]:
                continue
            target = posixpath.normpath(posixpath.join("" if folder == "." else folder, raw))
            if not target.startswith("../"):
                users.setdefault(target, set()).add(note)
    return users


def group_by_day(
    images: list[ImageInfo], newest_first: bool = True
) -> list[tuple[date, list[ImageInfo]]]:
    """``images`` in day groups (by file date), newest or oldest day first."""
    days: dict[date, list[ImageInfo]] = {}
    for info in sorted(images, key=lambda i: i.modified, reverse=newest_first):
        days.setdefault(info.day, []).append(info)
    return sorted(days.items(), key=lambda d: d[0], reverse=newest_first)


def trash_image(vault: Vault, path: str) -> str:
    """Move one image to the vault's trash; returns the trash path."""
    target = vault.asset_path("_.md", path)  # only an image inside the vault
    return vault.trash_move(target, path)
