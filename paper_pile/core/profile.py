"""The local profile: a name and an optional picture (PLAN §4.12). Nothing leaves the machine."""

import re
from pathlib import Path

import platformdirs

from paper_pile.core.assets import sniff_image
from paper_pile.core.fsutil import atomic_write_bytes

MAX_AVATAR_BYTES = 2 * 1024 * 1024
AVATAR_TYPES = {"png", "jpg", "gif", "webp"}  # no SVG: it can carry scripts
AVATAR_NAME = re.compile(r"^avatar\.(png|jpg|gif|webp)$")


class AvatarError(ValueError):
    """The picture cannot be used (the message is for the user)."""


def profile_dir() -> Path:
    """Where the picture lives: next to the global ``config.toml``."""
    return Path(platformdirs.user_config_dir("paper-pile"))


def initials(name: str) -> str:
    """Up to two capital letters for a round avatar without a picture ("Ada Lovelace" -> "AL")."""
    words = [w for w in re.split(r"[\s._-]+", name.strip()) if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


def save_avatar(data: bytes, directory: Path | None = None) -> str:
    """Store ``data`` as the profile picture and return its file name (``avatar.png``)."""
    folder = directory or profile_dir()
    if len(data) > MAX_AVATAR_BYTES:
        raise AvatarError("The picture is larger than 2 MB.")
    kind = sniff_image(data)
    if kind not in AVATAR_TYPES:
        raise AvatarError("Use a PNG, JPEG, GIF or WebP picture.")
    folder.mkdir(parents=True, exist_ok=True)
    remove_avatar(folder)
    name = f"avatar.{kind}"
    atomic_write_bytes(folder / name, data)
    return name


def remove_avatar(directory: Path | None = None) -> None:
    folder = directory or profile_dir()
    for path in folder.glob("avatar.*") if folder.is_dir() else []:
        if AVATAR_NAME.match(path.name):
            path.unlink(missing_ok=True)


def avatar_path(name: str, directory: Path | None = None) -> Path | None:
    """The picture file for the configured name, or ``None`` (only ``avatar.<ext>`` qualifies)."""
    if not AVATAR_NAME.match(name):
        return None
    path = (directory or profile_dir()) / name
    return path if path.is_file() else None
