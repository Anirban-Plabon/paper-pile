"""File operations: tree listing, atomic read/write, trash, rename/move, duplicate."""

import logging
from pathlib import Path

log = logging.getLogger("paper_pile.vault")

META_DIR = ".paper-pile"


class VaultError(Exception):
    """The given vault path cannot be used (missing, not a directory, ...)."""


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
