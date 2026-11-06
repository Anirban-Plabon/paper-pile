"""Saved vault searches (PLAN_vault_agent P30.41): a vault question the user wants to ask
again — kept per vault in ``.paper-pile/searches.json`` and run again from the chat's menu.
The user's own list (not a cache): written atomically, a corrupt file reads as empty and is
kept aside. No UI imports.
"""

import json
import logging
from pathlib import Path

from paper_pile.core.fsutil import atomic_write_bytes
from paper_pile.core.vault import META_DIR

log = logging.getLogger("paper_pile.ai.vault.searches")

SEARCHES_FILE = "searches.json"
MAX_SEARCHES = 30


def searches_path(vault_root: Path) -> Path:
    return vault_root / META_DIR / SEARCHES_FILE


def saved_searches(vault_root: Path) -> list[str]:
    """The saved questions, newest first."""
    path = searches_path(vault_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        log.warning("could not read %s", path)
        return []
    items = data.get("searches") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [s for s in items if isinstance(s, str) and s.strip()][:MAX_SEARCHES]


def _write(vault_root: Path, items: list[str]) -> None:
    path = searches_path(vault_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"searches": items[:MAX_SEARCHES]}, ensure_ascii=False, indent=1)
    atomic_write_bytes(path, body.encode("utf-8"))


def save_search(vault_root: Path, question: str) -> bool:
    """Keep ``question`` (first in the list; a repeat moves up); False when it is empty."""
    text = " ".join(question.split())
    if not text:
        return False
    items = [s for s in saved_searches(vault_root) if s != text]
    _write(vault_root, [text, *items])
    return True


def remove_search(vault_root: Path, question: str) -> None:
    items = saved_searches(vault_root)
    if question in items:
        _write(vault_root, [s for s in items if s != question])
