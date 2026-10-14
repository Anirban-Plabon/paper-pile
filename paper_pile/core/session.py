"""Open tabs, last vault, and session restore.

Two small pieces of state live here:
  * the *last vault* (global, in the user state dir), so ``paper-pile`` can reopen it;
  * the per-vault *session* (``<vault>/.paper-pile/session.json``): pane layout, mode, tabs.
Both are tolerant on read (missing or corrupt -> defaults) and never fatal on write.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import platformdirs

from paper_pile.core.fsutil import atomic_write_bytes

log = logging.getLogger("paper_pile.session")

_LAST_VAULT_FILE = "last_vault.json"
SESSION_FILE = "session.json"
META_DIR = ".paper-pile"

Mode = Literal["live", "source"]
PANES = ("left", "right")
DEFAULT_WIDTHS = {"left": 260, "right": 340}


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


@dataclass
class SessionState:
    tabs: list[str] = field(default_factory=list)
    active: str | None = None
    pane_widths: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WIDTHS))
    panes_open: dict[str, bool] = field(default_factory=lambda: {p: True for p in PANES})
    mode: Mode = "live"


def _session_path(vault: Path) -> Path:
    return vault / META_DIR / SESSION_FILE


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def load_session(vault: Path) -> SessionState:
    """Read the vault's session, keeping only well-formed fields."""
    state = SessionState()
    try:
        data = json.loads(_session_path(vault).read_text())
    except (FileNotFoundError, ValueError, OSError):
        return state
    if not isinstance(data, dict):
        return state
    tabs = data.get("tabs")
    if isinstance(tabs, list) and all(isinstance(t, str) for t in tabs):
        state.tabs = cast(list[str], tabs)
    if isinstance(data.get("active"), str):
        state.active = data["active"]
    for pane in PANES:
        widths, opens = data.get("pane_widths"), data.get("panes_open")
        if isinstance(widths, dict) and (w := _positive_int(widths.get(pane))):
            state.pane_widths[pane] = w
        if isinstance(opens, dict) and isinstance(opens.get(pane), bool):
            state.panes_open[pane] = opens[pane]
    if data.get("mode") in ("live", "source"):
        state.mode = data["mode"]
    return state


def save_session(vault: Path, state: SessionState) -> None:
    """Persist the session atomically. Failure is logged, never fatal."""
    path = _session_path(vault)
    payload = {
        "tabs": state.tabs,
        "active": state.active,
        "pane_widths": state.pane_widths,
        "panes_open": state.panes_open,
        "mode": state.mode,
    }
    try:
        path.parent.mkdir(exist_ok=True)
        atomic_write_bytes(path, json.dumps(payload, indent=2).encode("utf-8"))
    except OSError:
        log.warning("could not save session", exc_info=True)
