"""The app's folders in a vault (PLAN §6 P13): memories, images, daily notes and templates.

Each is a setting (vault-relative; the memories folder may also be absolute). The defaults are
the dot folders ``.memory``, ``.image``, ``.daily-notes`` and ``.template``, created in every
vault when it is opened. *Clear* moves a folder's contents to the vault's trash (never the
vault root, never the app's own data).
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from paper_pile.core.ai.chats import CHATS_DIR, chats_folder, move_chats
from paper_pile.core.config import Config
from paper_pile.core.session import META_DIR
from paper_pile.core.vault import TRASH_DIR, Vault

log = logging.getLogger("paper_pile.vault_folders")


@dataclass(frozen=True, slots=True)
class AppFolder:
    key: str  # the setting
    label: str
    default: str


FOLDERS = (
    AppFolder("ai.chats_folder", "Memories", ".memory"),
    AppFolder("vault.images_folder", "Images", ".image"),
    AppFolder("vault.daily_notes_folder", "Daily notes", ".daily-notes"),
    AppFolder("vault.templates_folder", "Templates", ".template"),
)
BY_KEY = {f.key: f for f in FOLDERS}


def folder_path(vault: Path, key: str, value: str) -> Path:
    """The absolute folder a setting value names ("" = the vault root, except for memories)."""
    if key == "ai.chats_folder":
        return chats_folder(vault, value)
    clean = value.strip().strip("/")
    return vault / clean if clean else vault


DAILY_TEMPLATES = "daily"  # daily-note templates: a folder inside the templates folder


def daily_templates_folder(templates_folder: str) -> str:
    """Where daily-note templates are kept by default ("" without a templates folder)."""
    clean = templates_folder.strip().strip("/")
    return f"{clean}/{DAILY_TEMPLATES}" if clean else ""


def ensure_folders(vault: Path, config: Config) -> None:
    """Create each app folder that is missing, and the daily-note templates folder inside the
    templates folder (a failure is logged, never fatal)."""
    paths = [folder_path(vault, f.key, str(config.get(f.key, f.default) or "")) for f in FOLDERS]
    daily = daily_templates_folder(str(config.get("vault.templates_folder", ".template") or ""))
    if daily:
        paths.append(vault / daily)
    for path in paths:
        if path == vault:
            continue
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.warning("could not create %s", path)


def move_old_chats(vault: Path, config: Config) -> int:
    """Chats saved before ``.memory`` existed (``.paper-pile/chats``) move into the memories
    folder, once, unless the user chose another place for them."""
    old = vault / META_DIR / CHATS_DIR
    target = folder_path(vault, "ai.chats_folder", str(config.get("ai.chats_folder", "") or ""))
    if not old.is_dir() or target != vault / ".memory":
        return 0
    moved = move_chats(old, target)
    if moved:
        log.info("moved %d chats from %s to %s", moved, old, target)
    return moved


def files_in(folder: Path) -> int:
    """How many files a folder holds (all levels); 0 if it does not exist."""
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.rglob("*") if p.is_file())


def can_clear(vault: Path, folder: Path) -> bool:
    """Never the vault itself, a folder holding it, or the app's own data."""
    root, target = vault.resolve(), folder.resolve()
    if target == root or root.is_relative_to(target):
        return False
    for own in (root / META_DIR, root / TRASH_DIR):
        if target == own or target.is_relative_to(own):
            return False
    return True


def clear_folder(vault: Vault, folder: Path) -> int:
    """Move everything inside ``folder`` to ``<vault>/.trash/<stamp>/`` (one stamp; the folder
    itself stays). Returns how many files went."""
    if not can_clear(vault.root, folder) or not folder.is_dir():
        raise ValueError(f"cannot clear {folder}")
    count = files_in(folder)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
    try:
        base = folder.resolve().relative_to(vault.root).as_posix()
    except ValueError:  # outside the vault (a memories folder): filed under its name
        base = folder.name
    for child in sorted(folder.iterdir()):
        vault.trash_move(child, f"{base}/{child.name}", stamp)
    return count
