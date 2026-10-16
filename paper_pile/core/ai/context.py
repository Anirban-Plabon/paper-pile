"""What the AI gets to see: the selection, the open note, mentioned notes, open tabs and linked
notes, filled in that order until a token budget is used up (PLAN §4.11).

Tokens are estimated as characters / 4. Every part is cut at a line boundary when it does not fit
and marked ``[truncated]``; later parts that no longer fit are left out. Nothing here talks to a
model or to the UI.
"""

import math
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from paper_pile.core.links import parse_wikilink, resolve_md_link, resolve_wikilink
from paper_pile.core.parser import note_links
from paper_pile.core.vault import Vault, VaultError

CHARS_PER_TOKEN = 4
DEFAULT_BUDGET = 6000
RESERVED_TOKENS = 250  # the instructions, the question and some room for the answer's start
MIN_PART_TOKENS = 40  # a part with less room than this is left out
MAX_LINKED = 8
TRUNCATED = "\n…[truncated]"

Kind = Literal["selection", "note", "mention", "tab", "linked"]
# share of the whole budget one part of a kind may take (the selection may take everything)
_SHARE: dict[Kind, float] = {
    "selection": 1.0,
    "note": 0.6,
    "mention": 0.25,
    "tab": 0.1,
    "linked": 0.08,
}
_HEADINGS: dict[Kind, str] = {
    "selection": "Selected text",
    "note": "Current note",
    "mention": "Mentioned note",
    "tab": "Open note",
    "linked": "Linked note",
}
_MENTION = re.compile(r"@\[\[([^\[\]\n]+)\]\]|(?<![\w@])@([^\s@\[\]]+)")


@dataclass(slots=True)
class EditorSnapshot:
    """What the AI features need to know about the editor right now."""

    path: str | None = None
    text: str = ""
    selection: str = ""
    tabs: list[tuple[str, str]] = field(default_factory=list)


class BacklinkSource(Protocol):
    def backlinks(self, target: str) -> Sequence[object]: ...


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


@dataclass(frozen=True, slots=True)
class ContextPart:
    kind: Kind
    title: str  # what the model is told this is ("Current note: notes/a.md")
    path: str | None
    text: str
    truncated: bool = False

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


@dataclass(slots=True)
class Context:
    budget: int
    parts: list[ContextPart] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # @mentions that matched no note

    @property
    def used(self) -> int:
        return sum(p.tokens for p in self.parts)

    def of(self, kind: Kind) -> list[ContextPart]:
        return [p for p in self.parts if p.kind == kind]

    def summary(self) -> str:
        """One line for the UI: what was sent along."""
        bits: list[str] = []
        for kind, label in (
            ("selection", "selection"),
            ("note", "note"),
            ("mention", "mentioned"),
            ("tab", "tabs"),
            ("linked", "linked"),
        ):
            found = self.of(kind)  # type: ignore[arg-type]
            if found:
                bits.append(label if kind in {"selection", "note"} else f"{len(found)} {label}")
        cut = " (some cut)" if any(p.truncated for p in self.parts) else ""
        return ("Context: " + ", ".join(bits) + cut) if bits else "No context"

    def system_prompt(self, user_name: str = "") -> str:
        who = f" The user is called {user_name}." if user_name else ""
        head = (
            "You are the assistant inside paper-pile, a local markdown note app. Answer in "
            "markdown; write math as $...$ (inline) or $$...$$ (display). Be direct and keep "
            f"to what was asked.{who}"
        )
        if not self.parts:
            return head
        blocks = [f"## {p.title}\n{p.text}" for p in self.parts]
        return head + "\n\nThe user's notes, for context:\n\n" + "\n\n".join(blocks)


def extract_mentions(text: str) -> list[str]:
    """Note names mentioned in a chat message: ``@[[Some note]]`` or ``@word``."""
    names: list[str] = []
    for m in _MENTION.finditer(text):
        name = (m.group(1) or m.group(2) or "").strip().rstrip(".,;:!?)")
        if name and name not in names:
            names.append(name)
    return names


def _cut(text: str, max_tokens: int) -> tuple[str, bool]:
    limit = max(0, max_tokens) * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    newline = cut.rfind("\n")
    if newline > limit * 0.5:
        cut = cut[:newline]
    return cut.rstrip() + TRUNCATED, True


class _Builder:
    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.remaining = max(0, budget - RESERVED_TOKENS)
        self.context = Context(budget)
        self.seen: set[str] = set()

    def add(self, kind: Kind, title: str, path: str | None, text: str) -> bool:
        if not text.strip() or (path is not None and path in self.seen):
            return False
        room = min(self.remaining, int(self.budget * _SHARE[kind]))
        if room < MIN_PART_TOKENS:
            return False
        body, truncated = _cut(text.strip("\n"), room)
        part = ContextPart(
            kind, f"{_HEADINGS[kind]}: {title}" if title else _HEADINGS[kind], path, body, truncated
        )
        self.context.parts.append(part)
        self.remaining -= part.tokens
        if path is not None:
            self.seen.add(path)
        return True


def _read(vault: Vault, path: str) -> str | None:
    try:
        return vault.read_text(path)
    except VaultError:
        return None


def _outgoing(text: str, source: str, paths: Collection[str]) -> list[str]:
    found: list[str] = []
    for ref in note_links(text):
        if ref.kind == "wiki":
            target = parse_wikilink(ref.raw)
            path = resolve_wikilink(target.note, source, paths) if target and target.note else None
        else:
            path = resolve_md_link(ref.raw, source, paths)
        if path and path != source and path not in found:
            found.append(path)
    return found


def build_context(
    vault: Vault,
    *,
    current_path: str | None,
    current_text: str = "",
    selection: str = "",
    mentions: Sequence[str] = (),
    open_tabs: Sequence[tuple[str, str]] = (),
    include_tabs: bool = False,
    index: BacklinkSource | None = None,
    budget: int = DEFAULT_BUDGET,
) -> Context:
    """Fill the context in priority order within ``budget`` tokens (see the module docstring).

    ``open_tabs`` is ``(path, text)`` of every open note; it is used only when ``include_tabs``.
    """
    b = _Builder(budget)
    paths = list(vault.walk_notes())
    if selection.strip():
        b.add("selection", "", None, selection)
    if current_path and current_text.strip():
        b.add("note", current_path, current_path, current_text)
    for name in mentions:
        path = resolve_wikilink(name, current_path or "", paths)
        text = _read(vault, path) if path else None
        if path is None or text is None:
            b.context.missing.append(name)
        elif path != current_path:
            b.add("mention", path, path, text)
    if include_tabs:
        for path, text in open_tabs:
            if path != current_path:
                b.add("tab", path, path, text)
    if current_path:
        linked = _outgoing(current_text, current_path, paths)
        if index is not None:
            for hit in index.backlinks(current_path):
                src = getattr(hit, "src", "")
                if src and src not in linked:
                    linked.append(src)
        for path in linked[:MAX_LINKED]:
            text = _read(vault, path)
            if text is not None:
                b.add("linked", path, path, text)
    return b.context
