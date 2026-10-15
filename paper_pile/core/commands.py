"""Slash command registry and actions (PLAN §4.8).

Commands are registered with the :func:`command` decorator. A command is a function from a
:class:`CommandContext` to an :data:`Action`; the GUI never interprets what a command *does*: the
editor sends the chosen id, Python returns an action, and the editor applies it. Searching
(fuzzy filter, grouping, recently used first) also lives here so a future TUI shares it.

    @command("h2", "Heading 2", group="Basic blocks", icon="h2", hint="##", aliases=["heading"])
    def h2(ctx: CommandContext) -> Action:
        return ReplaceLinePrefix("## ")
"""

import logging
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from paper_pile.core.config import Config
from paper_pile.core.vault import Vault

log = logging.getLogger("paper_pile.commands")

RECENT_LIMIT = 5
RECENT_GROUP = "Recent"
# The order groups appear in; a group not listed here comes after these, in registration order.
GROUP_ORDER = ("Basic blocks", "Code & math", "Diagrams", "Media", "Links", "Insert", "AI")


# ---- actions: what the editor is asked to do -----------------------------------------------


@dataclass(frozen=True, slots=True)
class Insert:
    """Insert ``text`` at the caret (replacing the typed ``/query``); the caret then goes
    ``cursor_offset`` characters from the start of the inserted text (default: its end)."""

    text: str
    cursor_offset: int | None = None


@dataclass(frozen=True, slots=True)
class ReplaceLinePrefix:
    """Make the current line start with ``prefix`` instead of any heading/list/quote marker."""

    prefix: str


@dataclass(frozen=True, slots=True)
class ReplaceSelection:
    text: str


@dataclass(frozen=True, slots=True)
class OpenNote:
    path: str


@dataclass(frozen=True, slots=True)
class OpenPicker:
    """Ask the user to pick something (``"note"``, ``"image"``, ``"template"``); the result comes
    back to the command that opened it."""

    kind: str
    command_id: str = ""


@dataclass(frozen=True, slots=True)
class StreamInsert:
    """Insert text as it arrives (AI commands)."""

    chunks: Callable[[], AsyncIterator[str]]


Action = Insert | ReplaceLinePrefix | ReplaceSelection | OpenNote | OpenPicker | StreamInsert


@dataclass(frozen=True, slots=True)
class CommandContext:
    note_path: str
    text: str  # the note as the editor holds it
    cursor: int  # caret offset in ``text``
    selection: tuple[int, int] | None = None
    vault: Vault | None = None
    config: Config | None = None
    ai: Any = None  # the AI provider (P7); commands that need it check for None

    @property
    def selected_text(self) -> str:
        return self.text[self.selection[0] : self.selection[1]] if self.selection else ""


Handler = Callable[[CommandContext], Action]
Predicate = Callable[[CommandContext], bool]


@dataclass(frozen=True, slots=True)
class Command:
    id: str
    title: str
    group: str
    handler: Handler
    icon: str = ""
    hint: str = ""  # the markdown it produces, shown right-aligned
    subtitle: str = ""
    badge: str = ""
    aliases: tuple[str, ...] = ()
    when: Predicate | None = None  # hidden (not an error) when this returns False

    def available(self, ctx: CommandContext | None) -> bool:
        return self.when is None or ctx is None or bool(self.when(ctx))

    def as_json(self) -> dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "badge": self.badge,
            "group": self.group,
            "icon": self.icon,
            "hint": self.hint,
        }


@dataclass(frozen=True, slots=True)
class CommandGroup:
    name: str
    commands: tuple[Command, ...]


class UnknownCommandError(KeyError):
    pass


# ---- matching ------------------------------------------------------------------------------


def match_score(query: str, text: str) -> int | None:
    """How well ``query`` matches ``text`` (higher is better), or ``None`` if it does not.

    Exact > prefix > start of a word > substring > letters in order (a fuzzy match, scored down
    for gaps). Case-insensitive; an empty query matches everything equally.
    """
    q, t = query.strip().lower(), text.lower()
    if not q:
        return 0
    if t == q:
        return 100
    if t.startswith(q):
        return 90
    if any(word.startswith(q) for word in t.replace("-", " ").replace("_", " ").split()):
        return 75
    if q in t:
        return 60
    pos, gaps = -1, 0
    for ch in q:
        nxt = t.find(ch, pos + 1)
        if nxt < 0:
            return None
        gaps += nxt - pos - 1 if pos >= 0 else 0
        pos = nxt
    return max(1, 40 - gaps)


def push_recent(recents: Sequence[str], command_id: str, limit: int = RECENT_LIMIT) -> list[str]:
    """``recents`` with ``command_id`` moved to the front (most recent first), capped."""
    return [command_id, *(r for r in recents if r != command_id)][:limit]


# ---- the registry --------------------------------------------------------------------------


@dataclass
class CommandRegistry:
    _commands: dict[str, Command] = field(default_factory=dict)

    def register(self, cmd: Command) -> Command:
        if cmd.id in self._commands:
            raise ValueError(f"duplicate command id: {cmd.id!r}")
        self._commands[cmd.id] = cmd
        return cmd

    def get(self, command_id: str) -> Command:
        try:
            return self._commands[command_id]
        except KeyError:
            raise UnknownCommandError(command_id) from None

    def all(self, ctx: CommandContext | None = None) -> list[Command]:
        return [c for c in self._commands.values() if c.available(ctx)]

    def run(self, command_id: str, ctx: CommandContext) -> Action:
        """Execute a command. Unknown or currently unavailable ids are refused."""
        cmd = self.get(command_id)
        if not cmd.available(ctx):
            raise UnknownCommandError(command_id)
        return cmd.handler(ctx)

    def search(
        self,
        query: str = "",
        ctx: CommandContext | None = None,
        recents: Iterable[str] = (),
    ) -> list[CommandGroup]:
        """Commands matching ``query`` (name, aliases, id), grouped, empty groups left out.

        With no query, recently used commands (most recent first, at most five) are listed first
        in their own "Recent" group and everything else follows in its group. With a query, best
        match first; ties go to the more recently used command.
        """
        rank = {cid: i for i, cid in enumerate(list(recents)[:RECENT_LIMIT])}
        order = {cid: i for i, cid in enumerate(self._commands)}
        scored: list[tuple[int, Command]] = []
        for cmd in self.all(ctx):
            score = self._score(query, cmd)
            if score is not None:
                scored.append((score, cmd))
        scored.sort(key=lambda sc: (-sc[0], rank.get(sc[1].id, 99), order[sc[1].id]))
        groups: dict[str, list[Command]] = {}
        if query.strip():
            for _score, cmd in scored:
                groups.setdefault(cmd.group, []).append(cmd)
            return [CommandGroup(name, tuple(cmds)) for name, cmds in groups.items()]
        recent = sorted((c for _s, c in scored if c.id in rank), key=lambda c: rank[c.id])
        rest = sorted((c for _s, c in scored if c.id not in rank), key=lambda c: order[c.id])
        for cmd in rest:
            groups.setdefault(cmd.group, []).append(cmd)
        known = [g for g in GROUP_ORDER if g in groups]
        extra = [g for g in groups if g not in GROUP_ORDER]
        result = [CommandGroup(name, tuple(groups[name])) for name in (*known, *extra)]
        if recent:
            result.insert(0, CommandGroup(RECENT_GROUP, tuple(recent)))
        return result

    @staticmethod
    def _score(query: str, cmd: Command) -> int | None:
        best: int | None = None
        for i, text in enumerate((cmd.title, *cmd.aliases, cmd.id)):
            score = match_score(query, text)
            if score is not None:
                score = score if i == 0 else score - 5  # the title is the most specific name
                best = score if best is None else max(best, score)
        return best


def groups_json(groups: Sequence[CommandGroup]) -> list[dict[str, Any]]:
    """What the editor needs to draw the menu."""
    return [{"group": g.name, "items": [c.as_json() for c in g.commands]} for g in groups]


REGISTRY = CommandRegistry()


def command(
    command_id: str,
    title: str,
    *,
    group: str,
    icon: str = "",
    hint: str = "",
    subtitle: str = "",
    badge: str = "",
    aliases: Sequence[str] = (),
    when: Predicate | None = None,
    registry: CommandRegistry | None = None,
) -> Callable[[Handler], Handler]:
    """Register the decorated function as a slash command (on the default registry)."""

    def decorate(handler: Handler) -> Handler:
        (registry or REGISTRY).register(
            Command(
                command_id,
                title,
                group,
                handler,
                icon=icon,
                hint=hint,
                subtitle=subtitle,
                badge=badge,
                aliases=tuple(aliases),
                when=when,
            )
        )
        return handler

    return decorate
