"""How folders look in the file tree: colour, icon, pinned (user 2026-11-22, PLAN §4.39).

View state, kept per vault in ``<vault>/.paper-pile/folders.json`` (like the table widths) and
never in the folders themselves: losing the file loses nothing but the looks::

    {"looks": {"Projects": {"color": "red", "icon": "briefcase"}}, "pinned": ["Projects"]}

Colours are the eight palette names of ``core.formatting.COLORS`` (2 × 4 in the picker); icons
are sixteen Lucide names (4 × 4). Unknown values in the file are dropped. Renames and moves
rewrite every path under the moved folder; a deleted folder's entries go.
"""

import json
import logging
from pathlib import Path

from paper_pile.core.formatting import COLORS
from paper_pile.core.fsutil import atomic_write_bytes

log = logging.getLogger("paper_pile.folder_looks")

LOOKS_FILE = "folders.json"
FOLDER_COLORS: tuple[str, ...] = tuple(COLORS)  # gray, red, orange, yellow, green, blue, ...
FOLDER_ICONS: tuple[str, ...] = (
    "folder",
    "book-open",
    "briefcase",
    "graduation-cap",
    "code",
    "flask-conical",
    "lightbulb",
    "star",
    "heart",
    "image",
    "music",
    "calendar",
    "users",
    "archive",
    "globe",
    "inbox",
)


class FolderLooks:
    """The store for one vault. Reads once; every change is written at once (it is tiny)."""

    def __init__(self, vault: Path) -> None:
        self._file = vault / ".paper-pile" / LOOKS_FILE
        self._looks: dict[str, dict[str, str]] = {}
        self._pinned: list[str] = []
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return
        if not isinstance(raw, dict):
            return
        looks = raw.get("looks")
        if isinstance(looks, dict):
            for path, look in looks.items():
                if isinstance(path, str) and path and isinstance(look, dict):
                    clean = _clean(look)
                    if clean:
                        self._looks[path] = clean
        pinned = raw.get("pinned")
        if isinstance(pinned, list):
            self._pinned = list(dict.fromkeys(p for p in pinned if isinstance(p, str) and p))

    def _save(self) -> None:
        data = {"looks": self._looks, "pinned": self._pinned}
        try:
            blob = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self._file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(self._file, blob)
        except OSError:
            log.warning("could not save folder looks to %s", self._file, exc_info=True)

    # ---- reading ------------------------------------------------------------------------

    def color(self, path: str) -> str:
        """The folder's palette name, ``""`` = the default (accent)."""
        return self._looks.get(path, {}).get("color", "")

    def icon(self, path: str) -> str:
        """The folder's icon name (``"folder"`` when none was chosen)."""
        return self._looks.get(path, {}).get("icon", "folder")

    def pinned(self) -> list[str]:
        return list(self._pinned)

    def is_pinned(self, path: str) -> bool:
        return path in self._pinned

    # ---- changing -----------------------------------------------------------------------

    def set_color(self, path: str, color: str) -> bool:
        """``""`` goes back to the default; an unknown name changes nothing."""
        if color and color not in FOLDER_COLORS:
            return False
        return self._set(path, "color", color)

    def set_icon(self, path: str, icon: str) -> bool:
        """``""`` or ``"folder"`` goes back to the plain folder; an unknown name changes nothing."""
        if icon and icon not in FOLDER_ICONS:
            return False
        return self._set(path, "icon", "" if icon == "folder" else icon)

    def reset(self, path: str) -> bool:
        """Default colour and icon (the pin stays)."""
        if path not in self._looks:
            return False
        del self._looks[path]
        self._save()
        return True

    def set_pinned(self, path: str, on: bool) -> bool:
        if on == (path in self._pinned) or not path:
            return False
        if on:
            self._pinned.append(path)
        else:
            self._pinned.remove(path)
        self._save()
        return True

    def renamed(self, old: str, new: str) -> bool:
        """``old`` (a folder or note) became ``new``: entries at or under it follow."""

        def move(p: str) -> str:
            return new + p[len(old) :] if p == old or p.startswith(old + "/") else p

        looks = {move(p): v for p, v in self._looks.items()}
        pinned = list(dict.fromkeys(move(p) for p in self._pinned))
        if looks == self._looks and pinned == self._pinned:
            return False
        self._looks, self._pinned = looks, pinned
        self._save()
        return True

    def deleted(self, path: str) -> bool:
        """``path`` went to the trash: its entries and those under it go."""

        def gone(p: str) -> bool:
            return p == path or p.startswith(path + "/")

        looks = {p: v for p, v in self._looks.items() if not gone(p)}
        pinned = [p for p in self._pinned if not gone(p)]
        if looks == self._looks and pinned == self._pinned:
            return False
        self._looks, self._pinned = looks, pinned
        self._save()
        return True

    def _set(self, path: str, key: str, value: str) -> bool:
        look = dict(self._looks.get(path, {}))
        if look.get(key, "") == value or not path:
            return False
        if value:
            look[key] = value
        else:
            look.pop(key, None)
        if look:
            self._looks[path] = look
        else:
            self._looks.pop(path, None)
        self._save()
        return True


def _clean(look: dict[object, object]) -> dict[str, str]:
    out: dict[str, str] = {}
    color, icon = look.get("color"), look.get("icon")
    if isinstance(color, str) and color in FOLDER_COLORS:
        out["color"] = color
    if isinstance(icon, str) and icon in FOLDER_ICONS and icon != "folder":
        out["icon"] = icon
    return out
