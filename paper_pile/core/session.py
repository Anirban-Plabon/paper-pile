"""Open tabs, last vault, and session restore."""

import json
import logging
from pathlib import Path

import platformdirs

log = logging.getLogger("paper_pile.session")

_LAST_VAULT_FILE = "last_vault.json"


def _state_dir(state_dir: Path | None) -> Path:
    return state_dir if state_dir is not None else Path(platformdirs.user_state_dir("paper-pile"))


def load_last_vault(state_dir: Path | None = None) -> Path | None:
    """Return the last opened vault if it still exists as a directory, else ``None``."""
    path = _state_dir(state_dir) / _LAST_VAULT_FILE
    try:
        raw = json.loads(path.read_text())["vault"]
    except (FileNotFoundError, KeyError, TypeError, ValueError, OSError):
        return None
    vault = Path(str(raw))
    return vault if vault.is_dir() else None


def save_last_vault(vault: Path, state_dir: Path | None = None) -> None:
    """Remember ``vault`` as the one to open next time. Failure is logged, never fatal."""
    directory = _state_dir(state_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / _LAST_VAULT_FILE).write_text(json.dumps({"vault": str(vault)}))
    except OSError:
        log.warning("could not remember last vault", exc_info=True)
