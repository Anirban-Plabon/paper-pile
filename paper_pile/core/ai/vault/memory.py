"""The vault memory file (PLAN_vault_agent §5.6, P30.28): ``.paper-pile/ai.md``, written by
the user — facts about how the vault is laid out ("daily notes in Journal/ as YYYY-MM-DD",
"one note per client with a Budget section"). It goes with every vault request so the agent
does not rediscover the layout each time. Like CLAUDE.md for a coding agent.

It is the user's own text: read here directly (the AI's read tools never open
``.paper-pile``), shown to the model as the user's description, cut at a size limit. An
agent-proposed addition is only ever a diff the user applies (M6). No UI imports.
"""

import logging
from pathlib import Path

from paper_pile.core.fsutil import atomic_write_bytes
from paper_pile.core.vault import META_DIR

log = logging.getLogger("paper_pile.ai.vault.memory")

MEMORY_FILE = "ai.md"
MAX_CHARS = 2000


def memory_path(vault_root: Path) -> Path:
    return vault_root / META_DIR / MEMORY_FILE


def load_memory(vault_root: Path, max_chars: int = MAX_CHARS) -> str:
    """The memory file's text, trimmed and cut at ``max_chars`` ("" when there is none)."""
    path = memory_path(vault_root)
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError):
        log.warning("could not read %s", path)
        return ""
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "\n…"


def read_memory_file(vault_root: Path) -> str:
    """The whole memory file as the user wrote it ("" when there is none) — for editing."""
    try:
        return memory_path(vault_root).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def save_memory(vault_root: Path, text: str) -> None:
    """Write the memory file (atomically). An empty text empties it — the file is the user's
    writing and is never deleted (rule 4)."""
    path = memory_path(vault_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = text.rstrip() + "\n" if text.strip() else ""
    atomic_write_bytes(path, body.encode("utf-8"))


def with_fact(text: str, fact: str) -> str:
    """The memory file with one more fact as a list line (a repeat is not added twice)."""
    line = "- " + " ".join(fact.split()).lstrip("-• ").strip()
    if line == "- " or line in text.splitlines():
        return text
    return (text.rstrip() + "\n" if text.strip() else "") + line + "\n"
