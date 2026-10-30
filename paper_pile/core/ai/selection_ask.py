"""The Ask box under a selection (PLAN §4.27): is a message a request to rewrite the selected
text, or a question about it? Decided by the first words (no model call), so the box knows at
once whether to dissolve into a rewrite or to grow into the mini chat. No UI imports here.
"""

import re
from dataclasses import dataclass
from typing import Literal

from paper_pile.core.commands import REGISTRY, Command, CommandContext

Role = Literal["user", "assistant"]

# words in front of the request that do not change what it asks for
_POLITE = frozenset({"please", "pls", "plz", "kindly", "can", "could", "would", "will", "you", "u"})
# a message starting with one of these asks for the text to be changed
_EDIT_VERBS = frozenset(
    {
        "rewrite",
        "rephrase",
        "reword",
        "modify",
        "change",
        "edit",
        "fix",
        "correct",
        "improve",
        "polish",
        "shorten",
        "condense",
        "lengthen",
        "expand",
        "simplify",
        "translate",
        "convert",
        "turn",
        "format",
        "reformat",
        "restructure",
        "replace",
        "make",
        "proofread",
    }
)
_WRITE_OBJECTS = frozenset({"it", "this", "that", "the"})  # "write it as…", not "write a poem"
_WORD = re.compile(r"[\w']+")


def wants_edit(message: str) -> bool:
    """True when ``message`` asks to rewrite / change the selected text (the first word after
    polite ones is an edit verb, or "write it / this …"); False for questions and anything else."""
    words = [w.lower() for w in _WORD.findall(message)]
    while words and words[0] in _POLITE:
        words.pop(0)
    if not words:
        return False
    if words[0] in _EDIT_VERBS:
        return True
    return words[0] == "write" and len(words) > 1 and words[1] in _WRITE_OBJECTS


@dataclass(frozen=True, slots=True)
class AskTurn:
    """One message of the mini chat: the user's question (or a command's task) or an answer."""

    role: Role
    text: str


AI_GROUP = "AI"  # commands_builtin.AI (not imported: that module registers the commands)
CARET_COMMANDS = frozenset({"ai-ask", "ai-continue"})  # about the caret, not the selection
DELETE = "delete"  # the box's own entry: remove the selected text (no AI)
_ORDER = ("ai-rewrite", "ai-fix", "ai-summarize", "ai-explain")  # with nothing typed after /
# picked for a selection in the editor's own slash menu, these open the box with it (PLAN §4.27)
BOX_AI_COMMANDS = frozenset(_ORDER)
# shorter titles and subtitles that fit the box (the registry's speak of Ctrl+J and the caret)
_SHOWN = {
    "ai-rewrite": ("Rewrite", "Replace it with a clearer version"),
    "ai-fix": ("Fix grammar", "Replace it, corrected"),
    "ai-summarize": ("Summarize", "Answer here"),
    "ai-explain": ("Explain", "Answer here"),
}


@dataclass(frozen=True, slots=True)
class BoxCommand:
    """One entry of the box's ``/`` list."""

    id: str
    title: str
    subtitle: str
    icon: str


def selection_commands(query: str, ctx: CommandContext) -> list[Command]:
    """The registry's AI commands that act on a selection (``ctx.selection`` set), best match
    for ``query`` first."""
    return [
        cmd
        for group in REGISTRY.search(query, ctx)
        for cmd in group.commands
        if cmd.group == AI_GROUP and cmd.id not in CARET_COMMANDS
    ]


def box_commands(query: str, ctx: CommandContext) -> list[BoxCommand]:
    """The box's ``/`` list for ``query``: the selection AI commands (Rewrite, Fix grammar,
    Summarize, Explain first when nothing is typed), then Delete."""
    found = selection_commands(query, ctx)
    if not query.strip():
        found.sort(key=lambda c: _ORDER.index(c.id) if c.id in _ORDER else len(_ORDER))
    out = [BoxCommand(c.id, *_SHOWN.get(c.id, (c.title, c.subtitle)), c.icon) for c in found]
    q = query.strip().lower()
    if not q or any(w.startswith(q) for w in ("delete", "remove", "erase")):
        out.append(BoxCommand(DELETE, "Delete", "Remove the selected text", "trash-2"))
    return out
