"""The Ask box under a selection (PLAN §4.27): its mini chat turns and its ``/`` list. Whether
a message changes the text or asks about it: ``ask_route``. No UI imports here.
"""

from dataclasses import dataclass
from typing import Literal

from paper_pile.core.ai.commands import AI_COMMAND_IDS
from paper_pile.core.commands import REGISTRY, Command, CommandContext

Role = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class AskTurn:
    """One message of the mini chat: the user's question (or a command's task) or an answer."""

    role: Role
    text: str


AI_GROUP = "AI"  # commands_builtin.AI (not imported: that module registers the commands)
CARET_COMMANDS = frozenset({"ai-ask"})  # about the caret, not the selection
DELETE = "delete"  # the box's own entry: remove the selected text (no AI)
# picked for a selection in the editor's own slash menu, these open the box with it (PLAN §4.27)
BOX_AI_COMMANDS = frozenset(AI_COMMAND_IDS)


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
    """The box's ``/`` list for ``query``: the AI commands (in the one list's order when nothing
    is typed, PLAN §4.28), then Delete."""
    found = selection_commands(query, ctx)
    if not query.strip():
        found.sort(key=lambda c: AI_COMMAND_IDS.index(c.id) if c.id in AI_COMMAND_IDS else 99)
    out = [BoxCommand(c.id, c.title, c.subtitle, c.icon) for c in found]
    q = query.strip().lower()
    if not q or any(w.startswith(q) for w in ("delete", "remove", "erase")):
        out.append(BoxCommand(DELETE, "Delete", "Remove the selected text", "trash-2"))
    return out
