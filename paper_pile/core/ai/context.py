"""What the AI gets to see: the selection, the open note, mentioned notes, open tabs and linked
notes, filled in that order until a token budget is used up (PLAN §4.11).

Tokens are estimated: four ASCII characters make one, and every other character (Bengali, CJK,
accented letters, emoji) one on its own — models split those scripts into many more pieces than
English, so counting them as a quarter would overfill the window (PLAN §4.26). Every part is cut
at a line boundary when it does not fit and marked ``[truncated]``; later parts that no longer fit
are left out. Nothing here talks to a model or to the UI.
"""

import math
import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Literal, Protocol

from paper_pile.core.links import parse_wikilink, resolve_md_link, resolve_wikilink
from paper_pile.core.parser import note_links
from paper_pile.core.vault import Vault, VaultError

CHARS_PER_TOKEN = 4
DEFAULT_BUDGET = 6000
RESERVED_TOKENS = 250  # the instructions, the question and some room for the answer's start
MIN_PART_TOKENS = 40  # a part with less room than this is left out
MAX_LINKED = 8
DIVIDER = "\n\n---\n\n"  # between the notes sent with a message and the message itself
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
    """About how many tokens ``text`` is (see the module docstring)."""
    ascii_chars = len(text.encode("ascii", "ignore"))
    return math.ceil(ascii_chars / CHARS_PER_TOKEN) + (len(text) - ascii_chars)


def cut_to_tokens(text: str, max_tokens: int) -> str:
    """The longest start of ``text`` that is at most ``max_tokens`` tokens."""
    limit = max(0, max_tokens)
    if estimate_tokens(text) <= limit:
        return text
    lo, hi = 0, min(len(text), limit * CHARS_PER_TOKEN)
    while lo < hi:  # the estimate grows with the length: find the last length that fits
        mid = (lo + hi + 1) // 2
        if estimate_tokens(text[:mid]) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


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

    def notes_block(self) -> str:
        """The parts as one markdown block ("" when there are none)."""
        if not self.parts:
            return ""
        blocks = [f"## {p.title}\n{p.text}" for p in self.parts]
        return "The user's notes, for context:\n\n" + "\n\n".join(blocks)

    def system_prompt(self, user_name: str = "", language: str = "", instructions: str = "") -> str:
        """The system prompt with the notes in it (one-shot prompts; the chat keeps the system
        prompt fixed and sends the notes with the message, see ``engine``)."""
        head = system_head(user_name, language, instructions)
        notes = self.notes_block()
        return f"{head}\n\n{notes}" if notes else head


def system_head(user_name: str = "", language: str = "", instructions: str = "") -> str:
    """Who the assistant is and how to answer: the same for every message of a chat."""
    who = f" The user is called {user_name}." if user_name else ""
    if language:
        who += f" Answer in {language} unless the user writes in another language."
    if instructions.strip():
        who += f" The user asks you to follow this: {instructions.strip()}"
    return (
        "You are the assistant inside paper-pile, a local markdown note app. Answer in "
        "markdown; write math as $...$ (inline) or $$...$$ (display). Be direct and keep "
        f"to what was asked. Notes the user shares come with their message.{who}"
    )


def extract_mentions(text: str) -> list[str]:
    """Note names mentioned in a chat message: ``@[[Some note]]`` or ``@word``."""
    names: list[str] = []
    for m in _MENTION.finditer(text):
        name = (m.group(1) or m.group(2) or "").strip().rstrip(".,;:!?)")
        if name and name not in names:
            names.append(name)
    return names


def _cut(text: str, max_tokens: int) -> tuple[str, bool]:
    cut = cut_to_tokens(text, max_tokens)
    if len(cut) == len(text):
        return text, False
    newline = cut.rfind("\n")
    if newline > len(cut) * 0.5:
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
    paths: Collection[str] | None = None,
    read: Callable[[str], str | None] | None = None,
) -> Context:
    """Fill the context in priority order within ``budget`` tokens (see the module docstring).

    ``open_tabs`` is ``(path, text)`` of every open note; it is used only when ``include_tabs``.
    ``paths`` (every note) and ``read`` (a note's text, None if unreadable) default to walking
    and reading the vault; the engine passes its cache.
    """
    b = _Builder(budget)
    if paths is None:
        paths = list(vault.walk_notes())
    if read is None:
        read = partial(_read, vault)
    if selection.strip():
        b.add("selection", "", None, selection)
    if current_path and current_text.strip():
        b.add("note", current_path, current_path, current_text)
    for name in mentions:
        path = resolve_wikilink(name, current_path or "", paths)
        text = read(path) if path else None
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
            text = read(path)
            if text is not None:
                b.add("linked", path, path, text)
    return b.context


_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*(\w*)")
_IMAGE = re.compile(r"!\[\[[^\[\]\n]+\]\]|!\[[^\[\]\n]*\]\([^()\n]*\)")


def source_view(text: str) -> str:
    """Markdown for showing a selection in the chat: text renders as in a note, but graphics
    (images, embeds, diagrams) stay as code so nothing is drawn or fetched."""
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        m = _FENCE.match(line)
        if fence is None and m:
            fence = m.group(2)[0] * 3
            lang = m.group(3).lower()
            out.append(f"{m.group(1)}{m.group(2)}{'text' if lang == 'mermaid' else lang}")
        elif fence is not None and m and m.group(2).startswith(fence) and not m.group(3):
            fence = None
            out.append(line)
        elif fence is not None:
            out.append(line)
        else:
            out.append(_IMAGE.sub(lambda i: f"`{i.group(0)}`", line))
    return "\n".join(out)
