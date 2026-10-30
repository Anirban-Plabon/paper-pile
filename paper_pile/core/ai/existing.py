"""Is what an AI edit adds already written? (PLAN §4.29, ``docs/AI_EDITS.md`` §4.7)

Checked in Python on every added text, whatever the model's plan said: each new item, row or
paragraph is compared with the note's blocks (by word 3-grams, and by item key for lists and
tables), and the whole new text with the best sections of other notes the full-text search
finds. The user is told — "May repeat line 42 (## Options)", "Similar text in [[x]]" — and
decides; another note is never changed. Pure; no UI imports.
"""

import re
from collections.abc import Sequence

from paper_pile.core.ai.blocks import Block
from paper_pile.core.ai.edit_context import item_key
from paper_pile.core.ai.issues import Issue
from paper_pile.core.parser import plain_line

IN_NOTE = 0.6  # share of the new text's 3-grams found in one block
IN_VAULT = 0.5
_WORD = re.compile(r"[^\W\d_]{3,}")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s+")
_DIVIDER = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")  # a table's |---|
ANSWER_NAMES = {
    "ai-summarize": ("summary", "tl;dr", "tldr", "in short"),
    "ai-explain": ("explanation", "explained"),
    "ai-outline": ("outline",),
}


def plain(text: str) -> str:
    return "\n".join(plain_line(line).text for line in text.split("\n"))


def shingles(text: str) -> set[tuple[str, str, str]]:
    words = [w.lower() for w in _WORD.findall(plain(text))]
    return {(words[i], words[i + 1], words[i + 2]) for i in range(len(words) - 2)}


def containment(a: str, b: str) -> float:
    """The share of ``a``'s 3-grams that are in ``b`` (0 when ``a`` has none)."""
    mine = shingles(a)
    return len(mine & shingles(b)) / len(mine) if mine else 0.0


def pieces(text: str) -> list[str]:
    """The new text as the parts to look for: its items / rows one by one, else paragraphs."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if lines and all(
        _ITEM.match(ln) or ln.lstrip().startswith("|") or ln[:1] in " \t" for ln in lines
    ):
        out: list[str] = []
        for ln in lines:
            if ln[:1] in " \t" and out and not _ITEM.match(ln):
                out[-1] += "\n" + ln
            elif not _DIVIDER.match(ln):
                out.append(ln)
        return out
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def _where(block: Block) -> str:
    return f"line {block.line}" + (f" ({block.path[-1]})" if block.path else "")


def in_note(new: str, blocks: Sequence[Block], note: str, skip: Sequence[str] = ()) -> list[Issue]:
    """Parts of ``new`` the note already has (``skip``: blocks the edit itself changes)."""
    keys: dict[str, dict[str, Block]] = {"item": {}, "table": {}}  # item / row keys
    for b in blocks:
        if b.kind in keys and b.id not in skip:
            text = b.text(note)
            lines = text.split("\n")[2:] if b.kind == "table" else [text]
            for line in lines:
                if key := item_key(line):
                    keys[b.kind].setdefault(key, b)
    found: list[Issue] = []
    seen: set[str] = set()
    for part in pieces(new):
        row = part.lstrip().startswith("|")
        key = item_key(part) if (_ITEM.match(part) or row) else ""
        same, other = (keys["table"], keys["item"]) if row else (keys["item"], keys["table"])
        hit = (same.get(key) or other.get(key)) if key else None  # its own kind first
        if hit is None:
            for b in blocks:
                if b.id in skip or b.fixed or b.kind == "heading":
                    continue
                if containment(part, b.text(note)) >= IN_NOTE:
                    hit = b
                    break
        if hit is not None and hit.id not in seen:
            seen.add(hit.id)
            found.append(Issue("exists", "warn", f"May repeat {_where(hit)}", data=hit.id))
    return found


def in_vault(new: str, hits: Sequence[tuple[str, str, str]]) -> list[Issue]:
    """Other notes' sections (``(path, heading, text)``) holding much of ``new``: told, with a
    link, never changed."""
    out: list[Issue] = []
    for path, heading, text in hits:
        if containment(new, text) >= IN_VAULT:
            name = path.removesuffix(".md")
            where = f"[[{name}#{heading}]]" if heading else f"[[{name}]]"
            out.append(Issue("elsewhere", "info", f"Similar text in {where}", data=path))
    return out


def existing_answer(command_id: str, blocks: Sequence[Block], note: str, near: str) -> Issue | None:
    """For an answer command: a heading or bold label in the section of block ``near`` that
    already names it ("## Summary", "**TL;DR**")."""
    names = ANSWER_NAMES.get(command_id, ())
    if not names:
        return None
    by_id = {b.id: b for b in blocks}
    section = by_id[near].path if near in by_id else ()
    for b in blocks:
        if b.path[: len(section)] != section and b.path != section[:-1]:
            continue
        first = plain(b.text(note).split("\n", 1)[0]).strip().lower()
        label = first.rstrip(":").strip("# ").strip()
        bold = b.text(note).lstrip().startswith(("**", "__"))
        if (b.kind == "heading" or bold) and any(label.startswith(n) for n in names):
            what = label.split(":")[0].strip().capitalize()
            said = f"This note already has a {what} (line {b.line})"
            return Issue("exists", "info", said, data=b.id)
    return None
