"""What an AI change asks for, without the model (PLAN §4.29, ``docs/AI_EDITS.md`` §4.1): may it
touch other places of the note (``scope``), how much may change (``size``), does it add content.
A hint, not a handler: a wrong guess only costs one plan call, or a warning the user can read.
No UI imports.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from paper_pile.core.ai.guards import STRUCTURE_WORDS, Size, asked_for

Scope = Literal["text", "note"]
SMALL = ("grammar", "spelling", "typo", "punctuation", "proofread", "fix", "correct")
STYLE = (
    "formal", "casual", "friendly", "shorter", "longer", "simpler", "clearer", "concise",
    "tone", "rephrase", "reword", "polish", "improve", "expand", "shorten", "simplify",
    "active voice", "passive", "professional", "polite",
)  # fmt: skip
ADD = ("add", "insert", "include", "append", "mention", "new section", "another", "also")
SMALL_GROUPS = frozenset({"fix"})
TEXT_GROUPS = frozenset({"length", "tone", "clarity", "language"})


@dataclass(frozen=True, slots=True)
class Intent:
    scope: Scope
    size: Size
    adds: bool  # the task puts new content in (not only changes what is there)
    asks_structure: bool


def edit_intent(command_id: str, instruction: str, groups: Sequence[str] = ()) -> Intent:
    """See the module docstring. ``groups``: the groups of the options the user ticked."""
    words = instruction.lower()
    adds = asked_for(words, ADD) or "content" in groups
    structure = asked_for(words, STRUCTURE_WORDS)
    if command_id == "ai-tone":
        return Intent("text", "large", False, structure)
    if groups and set(groups) <= SMALL_GROUPS:
        return Intent("text", "small", False, structure)
    if groups and set(groups) <= SMALL_GROUPS | TEXT_GROUPS:
        return Intent("text", "large", False, structure)
    if not adds and not structure:
        if words and _only(words, SMALL):
            return Intent("text", "small", False, False)
        if not words or asked_for(words, STYLE):
            return Intent("text", "large", False, False)
    return Intent("note", "medium", adds, structure)


def _only(words: str, small: Sequence[str]) -> bool:
    """The instruction asks for fixes and nothing else."""
    return (
        asked_for(words, small)
        and not asked_for(words, STYLE)
        and not re.search(r"\b(rewrite|change|make)\b", words)
    )
