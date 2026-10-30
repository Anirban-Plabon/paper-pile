"""Suggested prompts for the chat (PLAN §4.26): a few chips that fit what is attached, chosen by
rules (no model call), plus the user's own prompts from a markdown file (``ai.prompts_file``, one
``- `` item per prompt). A click fills the chat box; nothing is sent by itself. No UI imports.
"""

import logging
import re
from collections.abc import Sequence
from pathlib import Path

log = logging.getLogger("paper_pile.ai.prompts")

MAX_SHOWN = 3  # floating above the chat's box (P24: at most 3)
MAX_OWN = 20
MAX_FILE_CHARS = 20000

_BY_KIND: dict[str, tuple[str, ...]] = {
    "prose": ("Rewrite this more clearly", "Make it shorter", "Fix the grammar", "Explain this"),
    "code": ("Explain this code", "Find bugs in this code", "Add comments to this code"),
    "math": ("Explain this step by step", "Check this for mistakes"),
    "table": ("Summarize this table", "What patterns are in this table?"),
    "diagram": ("Explain this diagram", "Suggest improvements to this diagram"),
    "note": (
        "Summarize this note",
        "Outline this note",
        "List the key points",
        "What is still open?",
    ),
}
_TABLE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


def selection_kind(kind: str, text: str) -> str:
    """The suggestion group for an attached selection or block (its chip's ``kind``)."""
    if kind == "Code block":
        return "code"
    if kind == "Math block":
        return "math"
    if kind == "Diagram":
        return "diagram"
    t = text.strip()
    if t.startswith("```"):
        return "code"
    if t.startswith("$$"):
        return "math"
    if len(_TABLE.findall(t)) >= 2:
        return "table"
    return "prose"


def suggestions(kinds: Sequence[str], own: Sequence[str] = ()) -> list[str]:
    """Up to ``MAX_SHOWN`` prompts for what is attached (``kinds``: groups, most recent first),
    then the user's own; none when nothing is attached."""
    if not kinds:
        return []
    picked: list[str] = []
    for kind in dict.fromkeys(kinds):
        for prompt in _BY_KIND.get(kind, ()):
            if prompt not in picked:
                picked.append(prompt)
    first = picked[: max(1, MAX_SHOWN - len(own))] if own else picked[:MAX_SHOWN]
    return list(dict.fromkeys([*first, *own]))[:MAX_SHOWN]


def prompts_file(vault: Path, setting: str) -> Path | None:
    """The file ``ai.prompts_file`` names: absolute, ``~``, or relative to the vault."""
    chosen = setting.strip()
    if not chosen:
        return None
    path = Path(chosen).expanduser()
    return path if path.is_absolute() else vault / path


def load_prompts(path: Path | None) -> list[str]:
    """The ``- `` / ``* `` items of a markdown file (a missing file means none)."""
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
    except OSError:
        log.warning("cannot read the prompts file %s", path)
        return []
    found = [m.group(1).strip() for m in re.finditer(r"^[ \t]*[-*][ \t]+(.+)$", text, re.MULTILINE)]
    return list(dict.fromkeys(p for p in found if p))[:MAX_OWN]
