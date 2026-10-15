"""Images in notes: storage, naming, references and the lifecycle of a note's assets folder.

A note's images live in a hidden sibling folder, ``notes/mamba.md`` -> ``notes/.mamba.assets/``,
named by the hash of their bytes (so pasting the same picture twice stores it once). The note
refers to them with a plain relative markdown path, ``![image|480](.mamba.assets/a3f9c1d2e4b0.png)``
(the number after ``|`` is the display width, the Obsidian convention). The app owns that folder:
renaming, moving, duplicating or deleting a note takes its images along, and images no longer
referenced are moved to ``.trash`` (never unlinked).
"""

import hashlib
import logging
import posixpath
import re
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

from paper_pile.core.fsutil import atomic_write_bytes
from paper_pile.core.parser import image_spans
from paper_pile.core.rewrite import Edit, locate_spans, scan_destination
from paper_pile.core.vault import IMAGE_SUFFIXES, NOTE_SUFFIXES, InvalidPathError, VaultError

if TYPE_CHECKING:
    from paper_pile.core.vault import Vault

log = logging.getLogger("paper_pile.assets")

MAX_IMAGE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_WIDTH = 640  # a freshly inserted image is shown at most this wide
MIN_WIDTH, MAX_WIDTH = 20, 4000
_HASH_CHARS = 12


class ImageError(VaultError):
    """The data is not an image we accept (or is too big)."""


@dataclass(frozen=True, slots=True)
class SavedImage:
    name: str  # a3f9c1d2e4b0.png
    path: str  # vault-relative: notes/.mamba.assets/a3f9c1d2e4b0.png
    ref: str  # as written in the note: .mamba.assets/a3f9c1d2e4b0.png (percent-encoded)
    width: int | None  # suggested display width, None if unknown (SVG)
    new: bool  # False when the same picture was already stored


# ---- names and references --------------------------------------------------------------------


def _stem(note: str) -> str:
    return PurePosixPath(note).stem


def assets_prefix(note: str) -> str:
    """The folder name of a note's images: ``.mamba.assets``."""
    return f".{_stem(note)}.assets"


def assets_folder(note: str) -> str:
    """Vault-relative path of a note's images folder."""
    parent = PurePosixPath(note).parent.as_posix()
    prefix = assets_prefix(note)
    return prefix if parent == "." else f"{parent}/{prefix}"


def encode_ref(prefix: str, name: str) -> str:
    return quote(f"{prefix}/{name}", safe="/._-~")


def image_markdown(ref: str, width: int | None = None, alt: str = "image") -> str:
    """``![image|480](.mamba.assets/a3f9c1d2e4b0.png)``"""
    sized = f"{alt}|{width}" if width else alt
    return f"![{sized}]({ref})"


# ---- recognising images ----------------------------------------------------------------------


def sniff_image(data: bytes) -> str | None:
    """The file extension that matches the bytes, or ``None`` if they are not a known image."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == b"BM" and len(data) > 26:
        return "bmp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "avif"
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith((b"<svg", b"<?xml")) and b"<svg" in data[:2048].lower():
        return "svg"
    return None


def image_size(data: bytes) -> tuple[int, int] | None:
    """``(width, height)`` read from the file header (no image library), or ``None``."""
    try:
        kind = sniff_image(data)
        if kind == "png":
            w, h = struct.unpack(">II", data[16:24])
            return w, h
        if kind == "gif":
            w, h = struct.unpack("<HH", data[6:10])
            return w, h
        if kind == "bmp":
            w, h = struct.unpack("<ii", data[18:26])
            return abs(w), abs(h)
        if kind == "jpg":
            return _jpeg_size(data)
        if kind == "webp":
            return _webp_size(data)
    except (struct.error, IndexError):
        return None
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return w, h
        i += 2 + length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    kind = data[12:16]
    if kind == b"VP8 ":
        w, h = struct.unpack("<HH", data[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if kind == b"VP8L":
        bits = struct.unpack("<I", data[21:25])[0]
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b"VP8X":
        return (
            int.from_bytes(data[24:27], "little") + 1,
            int.from_bytes(data[27:30], "little") + 1,
        )
    return None


# ---- saving ----------------------------------------------------------------------------------


def save_image(vault: "Vault", note: str, data: bytes) -> SavedImage:
    """Store ``data`` as an image of ``note`` and return how to refer to it.

    The name is the first 12 hex digits of the SHA-256 of the bytes plus the extension the bytes
    really have (so a ``.png`` that is not a PNG is refused, not stored). The same picture twice
    is one file.
    """
    vault.resolve(note)  # a safe vault path (the note may not exist yet)
    if PurePosixPath(note).suffix.lower() not in NOTE_SUFFIXES:
        raise InvalidPathError(f"not a note: {note!r}")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(f"image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    ext = sniff_image(data)
    if ext is None or f".{ext}" not in IMAGE_SUFFIXES:
        raise ImageError("not a supported image (png, jpg, gif, webp, bmp, avif or svg)")
    name = f"{hashlib.sha256(data).hexdigest()[:_HASH_CHARS]}.{ext}"
    folder = vault.root / assets_folder(note)
    target = folder / name
    new = not target.exists()
    if new:
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, data)
    size = image_size(data)
    width = min(size[0], DEFAULT_MAX_WIDTH) if size and size[0] > 0 else None
    return SavedImage(
        name,
        f"{assets_folder(note)}/{name}",
        encode_ref(assets_prefix(note), name),
        width,
        new,
    )


# ---- what a note refers to -------------------------------------------------------------------


def referenced_files(text: str, note: str) -> set[str]:
    """File names in the note's own assets folder that ``text`` refers to as images."""
    own = assets_prefix(note)
    names: set[str] = set()
    for span in image_spans(text):
        path = posixpath.normpath(unquote(span.raw))
        head, _, name = path.rpartition("/")
        if head == own and name:
            names.add(name)
    return names


def asset_files(vault: "Vault", note: str) -> list[Path]:
    folder = vault.root / assets_folder(note)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file())


# ---- lifecycle ------------------------------------------------------------------------------


def sweep_orphans(vault: "Vault", note: str, text: str) -> list[str]:
    """Move images of ``note`` that ``text`` no longer refers to to the trash; remove the folder
    if nothing is left. Returns the trash paths."""
    keep = referenced_files(text, note)
    trashed: list[str] = []
    stamp = None
    for path in asset_files(vault, note):
        if path.name in keep or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        rel = f"{assets_folder(note)}/{path.name}"
        trashed.append(vault.trash_move(path, rel, stamp))
        stamp = stamp or PurePosixPath(trashed[0]).parts[1]
    _remove_if_empty(vault.root / assets_folder(note))
    return trashed


def _remove_if_empty(folder: Path) -> None:
    try:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        log.warning("could not remove empty assets folder %s", folder)


def move_assets(vault: "Vault", old_note: str, new_note: str) -> None:
    """The note was renamed or moved: its images folder follows (merging if the target exists)."""
    old, new = vault.root / assets_folder(old_note), vault.root / assets_folder(new_note)
    if old == new or not old.is_dir():
        return
    try:
        if not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
            return
        for item in old.iterdir():  # names are content hashes: an existing file is the same picture
            if not (new / item.name).exists():
                item.rename(new / item.name)
        _remove_if_empty(old)
    except OSError:
        log.exception("could not move the images of %s", old_note)


def duplicate_assets(vault: "Vault", src_note: str, dst_note: str) -> None:
    """A note was copied: the copy gets its own images folder and its references are updated."""
    old, new = vault.root / assets_folder(src_note), vault.root / assets_folder(dst_note)
    if not old.is_dir() or new.exists():
        return
    try:
        shutil.copytree(old, new)
        text = vault.read_text(dst_note)
        edits = plan_ref_edits(text, src_note, dst_note)
        if edits:
            from paper_pile.core.rewrite import apply_edits

            vault.write_text(dst_note, apply_edits(text, edits))
    except (OSError, VaultError):
        log.exception("could not copy the images of %s", src_note)


def trash_assets(vault: "Vault", note: str, stamp: str) -> None:
    """The note went to the trash: its images go to the same trash folder."""
    folder = vault.root / assets_folder(note)
    if folder.is_dir():
        vault.trash_move(folder, assets_folder(note), stamp)


def plan_ref_edits(text: str, old_note: str, new_note: str) -> list[Edit]:
    """Edits that point ``text``'s images at the new assets folder name after a rename.

    Only the folder part of an image path inside the note's own old assets folder changes
    (``.old.assets/x.png`` -> ``.new.assets/x.png``); everything else stays byte-identical.
    """
    old_prefix, new_prefix = assets_prefix(old_note), assets_prefix(new_note)
    if old_prefix == new_prefix:
        return []
    spans = image_spans(text)
    starts = locate_spans(text, spans)
    edits: list[Edit] = []
    for span, start in zip(spans, starts, strict=True):
        if start is None or posixpath.normpath(unquote(span.raw)).rpartition("/")[0] != old_prefix:
            continue
        found = scan_destination(span.source[1:])  # skip the "!"
        if found is None:
            continue
        d_start, d_end, _angle = found
        written = span.source[1 + d_start : 1 + d_end]
        for old_form, new_form in (
            (encode_ref(old_prefix, ""), encode_ref(new_prefix, "")),
            (f"{old_prefix}/", f"{new_prefix}/"),
        ):
            for lead in ("", "./"):
                if written.startswith(lead + old_form):
                    at = start + 1 + d_start + len(lead)
                    edits.append(Edit(at, at + len(old_form), new_form))
                    break
            else:
                continue
            break
    return edits


# ---- resizing -------------------------------------------------------------------------------


def clamp_width(width: int) -> int:
    return max(MIN_WIDTH, min(MAX_WIDTH, int(width)))


def set_width_edit(text: str, start: int, width: int) -> Edit | None:
    """The edit that sets the display width of the image written at ``text[start:]`` to
    ``width``: only the number after ``|`` in the alt text is touched (added if missing).
    ``None`` if there is no image at ``start``."""
    if text[start : start + 2] != "![":
        return None
    i, depth = start + 2, 1
    while i < len(text) and depth:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "\n":
            return None
        depth += (c == "[") - (c == "]")
        i += 1
    if depth or text[i : i + 1] != "(":
        return None
    alt_from, alt_to = start + 2, i - 1
    alt = text[alt_from:alt_to]
    width = clamp_width(width)
    m = re.search(r"\|\s*\d+\s*$", alt)
    if m:
        return Edit(alt_from + m.start(), alt_to, f"|{width}")
    return Edit(alt_to, alt_to, f"|{width}")
