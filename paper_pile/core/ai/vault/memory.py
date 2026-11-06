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
