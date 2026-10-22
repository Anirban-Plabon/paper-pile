"""Browsing the computer's folders to pick a vault ("Open vault"; works in ``--serve`` mode too,
where the browser cannot show the server's folders). Pure listing: nothing is created here."""

import logging
from pathlib import Path

log = logging.getLogger("paper_pile.folders")


def start_folder(current: Path | None) -> Path:
    """Where browsing starts: the folder holding the open vault, else the home folder."""
    if current is not None and current.parent.is_dir():
        return current.parent
    return Path.home()


def subfolders(folder: Path) -> list[Path]:
    """The visible folders inside ``folder``, sorted by name (case-insensitive). Hidden folders
    (``.name``) are left out; folders that cannot be read give an empty list."""
    try:
        entries = [e for e in folder.iterdir() if not e.name.startswith(".") and e.is_dir()]
    except OSError:
        log.info("cannot list %s", folder, exc_info=True)
        return []
    return sorted(entries, key=lambda e: e.name.lower())


def is_vault(folder: Path) -> bool:
    """Has this folder been opened as a vault before?"""
    return (folder / ".paper-pile").is_dir()
