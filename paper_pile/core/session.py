"""Open tabs, last vault, and session restore.

Two small pieces of state live here:
  * the *last vault* and the recent ones (global, in the user state dir), so ``paper-pile`` can
    reopen it and "Open vault" can list them;
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
MAX_RECENT_VAULTS = 8
MAX_RECENT_NOTES = 20  # the quick switcher lists these first
OUTLINE_HEIGHT = 220  # px: the Outline section under the file tree, by default
SESSION_FILE = "session.json"
META_DIR = ".paper-pile"

Mode = Literal["live", "source"]
PANES = ("left", "right")
DEFAULT_WIDTHS = {
    "left": 260,
    "right": 340,
    "settings": 720,
}  # settings: the right pane while it shows Settings


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


def load_recent_vaults(state_dir: Path | None = None) -> list[Path]:
    """Vaults opened before, newest first; only those that still exist as directories."""
    path = _state_dir(state_dir) / _LAST_VAULT_FILE
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("recent")
    names = [str(v) for v in raw] if isinstance(raw, list) else []
    if "vault" in data:
        names.insert(0, str(data["vault"]))
    seen: list[Path] = []
    for name in names:
        vault = Path(name)
        if vault not in seen and vault.is_dir():
            seen.append(vault)
    return seen[:MAX_RECENT_VAULTS]


def save_last_vault(vault: Path, state_dir: Path | None = None) -> None:
    """Remember ``vault`` as the one to open next time (and at the top of the recent vaults).
    Failure is logged, never fatal."""
    directory = _state_dir(state_dir)
    recent = [vault] + [v for v in load_recent_vaults(state_dir) if v != vault]
    data = {"vault": str(vault), "recent": [str(v) for v in recent[:MAX_RECENT_VAULTS]]}
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / _LAST_VAULT_FILE).write_text(json.dumps(data))
    except OSError:
        log.warning("could not remember last vault", exc_info=True)


@dataclass
class SessionState:
    tabs: list[str] = field(default_factory=list)
    active: str | None = None
    pane_widths: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WIDTHS))
    panes_open: dict[str, bool] = field(default_factory=lambda: {p: True for p in PANES})
    mode: Mode = "live"
    recent_commands: list[str] = field(default_factory=list)  # slash menu, newest first
    recent_notes: list[str] = field(default_factory=list)  # opened notes, newest first
    outline_open: bool = False  # the Outline section under the file tree
    outline_height: int = OUTLINE_HEIGHT


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
    widths, opens = data.get("pane_widths"), data.get("panes_open")
    for pane in DEFAULT_WIDTHS:
        if isinstance(widths, dict) and (w := _positive_int(widths.get(pane))):
            state.pane_widths[pane] = w
    for pane in PANES:
        if isinstance(opens, dict) and isinstance(opens.get(pane), bool):
            state.panes_open[pane] = opens[pane]
    if data.get("mode") in ("live", "source"):
        state.mode = data["mode"]
    recent = data.get("recent_commands")
    if isinstance(recent, list):
        state.recent_commands = [r for r in recent if isinstance(r, str)][:5]
    if isinstance(data.get("outline_open"), bool):
        state.outline_open = data["outline_open"]
    if height := _positive_int(data.get("outline_height")):
        state.outline_height = height
    notes = data.get("recent_notes")
    if isinstance(notes, list):
        state.recent_notes = [n for n in notes if isinstance(n, str)][:MAX_RECENT_NOTES]
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
        "recent_commands": state.recent_commands[:5],
        "recent_notes": state.recent_notes[:MAX_RECENT_NOTES],
        "outline_open": state.outline_open,
        "outline_height": state.outline_height,
    }
    try:
        path.parent.mkdir(exist_ok=True)
        atomic_write_bytes(path, json.dumps(payload, indent=2).encode("utf-8"))
    except OSError:
        log.warning("could not save session", exc_info=True)
