"""What the model sees of a note for an AI edit (PLAN §4.29, ``docs/AI_EDITS.md`` §4.3).

Not the whole note: the target blocks and the blocks *related* to the request in full, every
other block as one outline line, and all headings, so the model knows the note's structure and
every place that may need the same change ("three options", a second list or table of the same
items). Related blocks are found without the model: shared key terms, sibling lists and tables,
numbers next to key terms, the neighbours and the section heading of each target. Everything
fits a budget that scales with the model's window. Pure; no UI imports.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from paper_pile.core.ai.blocks import Block
from paper_pile.core.ai.context import cut_to_tokens, estimate_tokens
from paper_pile.core.index import query_words

OUTLINE_WORDS = 10
NUMBER_WORDS = [
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
]
_NUMBER = re.compile(r"\b(\d+|" + "|".join(NUMBER_WORDS) + r")\b", re.IGNORECASE)
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?")
_KEY = re.compile(r"\*\*(.+?)\*\*|__(.+?)__|\[\[([^\]|#]+)|\[([^\]]+)\]\(|`([^`]+)`")
_ITEM_MARK = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s+(?:\[[ xX]\]\s+)?")


@dataclass(frozen=True, slots=True)
class EditBudget:
    """Tokens for each part of an edit prompt (``docs/AI_EDITS.md`` §4.3, at 8192)."""

    window: int
    answer: int
    target: int
    related: int
    outline: int
    vault: int

    @classmethod
    def for_window(cls, window: int) -> "EditBudget":
        scale = window / 8192
        return cls(
            window,
            answer=max(256, int(512 * scale)),
            target=int(1800 * scale),
            related=int(1800 * scale),
            outline=int(1600 * scale),
            vault=int(450 * scale),
        )


@dataclass(frozen=True, slots=True)
class NoteView:
    text: str  # the note as numbered blocks, for the prompt
    full: tuple[str, ...]  # ids shown in full (targets first)
    folded: int  # blocks shown only as a count ("38 blocks under …")
    fits: bool  # False: the target alone is over its budget (go section by section, §5)


def stem(word: str) -> str:
    w = word.lower()
    if len(w) > 4 and w.endswith("es"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def key_terms(*texts: str) -> set[str]:
    """The words worth matching in ``texts`` (stemmed; common words left out)."""
    return {stem(w) for t in texts for w in query_words(t, most=40)}


def _terms_in(text: str) -> set[str]:
    return {stem(w) for w in _WORD.findall(text)}


def item_key(text: str) -> str:
    """What an item or a table row is "about": its first bold / link / code span, else its first
    words (lower case). Two lists with the same keys describe the same things."""
    body = _ITEM_MARK.sub("", text.split("\n", 1)[0]).strip().strip("|").strip()
    found = _KEY.search(body)
    if found:
        return next(g for g in found.groups() if g).strip().lower()
    if "|" in body:  # a table row: its first cell
        return body.split("|", 1)[0].strip().lower()
    return " ".join(_WORD.findall(body)[:4]).lower()


def structure_keys(block: Block, note: str) -> list[str]:
    """The item keys of a table block (its rows, no header) or of one item."""
    text = block.text(note)
    if block.kind == "table":
        rows = [r for r in text.split("\n") if r.strip()][2:]
        return [k for r in rows if (k := item_key(r))]
    return [item_key(text)] if block.kind == "item" else []


def _has_count(text: str, terms: set[str]) -> bool:
    """A number within 3 words of a key term ("we compare three options")."""
    words = _WORD.findall(text)
    stems = [stem(w) for w in words]
    for i, w in enumerate(words):
        if _NUMBER.fullmatch(w):
            near = stems[max(0, i - 3) : i + 4]
            if terms.intersection(near):
                return True
    return False


def related_blocks(
    blocks: Sequence[Block], note: str, targets: Iterable[str], terms: set[str]
) -> list[str]:
    """Ids of blocks related to the targets and the request (not the targets themselves),
    nearest to a target first."""
    target_ids = set(targets)
    index = {b.id: i for i, b in enumerate(blocks)}
    tpos = [index[t] for t in target_ids if t in index]
    if not tpos:
        return []
    # the keys of the lists and tables the targets are in, or that share terms
    keys: set[str] = set()
    for b in blocks:
        if b.id in target_ids or (b.kind in ("item", "table") and terms & _terms_in(b.text(note))):
            keys.update(structure_keys(b, note))
    target_lists = {b.list_id for b in blocks if b.id in target_ids and b.list_id}
    found: set[str] = set()
    for i, b in enumerate(blocks):
        if b.id in target_ids or b.kind == "front_matter":
            continue
        text = b.text(note)
        mine = _terms_in(text)
        if b.list_id and b.list_id in target_lists:
            found.add(b.id)  # the rest of the target's own list
        elif b.kind == "heading" and terms & mine or len(terms & mine) >= 2:
            found.add(b.id)
        elif keys and set(structure_keys(b, note)) & keys:
            found.add(b.id)  # a list or table about the same things
        elif terms & mine and any(k in text.lower() for k in keys):
            found.add(b.id)  # names one of those things ("Docker is the easiest option")
        elif _has_count(text, terms | {stem(k) for k in keys}):
            found.add(b.id)
        elif any(abs(i - t) == 1 for t in tpos):
            found.add(b.id)  # a neighbour
    for t in tpos:  # the heading of each target's section
        for b in reversed(blocks[:t]):
            if b.kind == "heading":
                found.add(b.id)
                break
    return sorted(found, key=lambda i: (min(abs(index[i] - t) for t in tpos), index[i]))


def outline_line(block: Block, note: str) -> str:
    """One line for a block shown only in outline."""
    text = block.text(note)
    if block.kind == "heading":
        return f"[{block.id}] {text.strip()}"
    if block.fixed:
        lines = text.count("\n") + 1
        what = "properties" if block.kind == "front_matter" else block.kind
        return f"[{block.id}] {what} ({lines} lines)"
    words = text.split()
    cut = " ".join(words[:OUTLINE_WORDS]) + (" …" if len(words) > OUTLINE_WORDS else "")
    if block.kind == "table":
        rows = max(0, text.count("\n") - 1)
        cut = f"{text.split(chr(10), 1)[0].strip()} ({rows} rows)"
    return f"[{block.id}] {block.kind}: {cut}"


def full_view(block: Block, note: str) -> str:
    return f"[{block.id}] {block.kind}\n{block.text(note)}"


def note_view(
    note: str,
    blocks: Sequence[Block],
    targets: Sequence[str],
    instruction: str,
    budget: EditBudget,
) -> NoteView:
    """The note for the prompt (see the module docstring)."""
    by_id = {b.id: b for b in blocks}
    target_ids = [t for t in targets if t in by_id]
    target_text = "\n".join(by_id[t].text(note) for t in target_ids)
    fits = estimate_tokens(target_text) <= budget.target
    terms = key_terms(instruction, target_text)
    full = list(target_ids)
    used = 0
    for rid in related_blocks(blocks, note, target_ids, terms):
        cost = estimate_tokens(by_id[rid].text(note))
        if by_id[rid].fixed or by_id[rid].kind == "heading":
            continue  # outline lines already show them
        if used + cost <= budget.related:
            full.append(rid)
            used += cost
    shown = set(full)
    lines = _outline(blocks, note, shown, budget.outline)
    folded = sum(n for _, n in lines if n)
    return NoteView("\n".join(text for text, _ in lines), tuple(full), folded, fits)


def _outline(
    blocks: Sequence[Block], note: str, shown: set[str], limit: int
) -> list[tuple[str, int]]:
    """``(line, folded count)`` per entry: blocks in ``shown`` in full, the rest as outline
    lines; while over ``limit`` tokens, runs of outline blocks are folded into one line each,
    farthest from a shown block first."""
    entries = [(b, full_view(b, note) if b.id in shown else outline_line(b, note)) for b in blocks]
    full_cost = sum(estimate_tokens(t) for b, t in entries if b.id in shown)

    def cost(es: list[tuple[str, int]]) -> int:
        return sum(estimate_tokens(t) for t, _ in es) - full_cost

    out: list[tuple[str, int]] = [(t, 0) for _, t in entries]
    if cost(out) <= limit:
        return out
    # fold each run of non-heading outline blocks, the runs farthest from what is shown first
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(blocks):
        if blocks[i].id in shown or blocks[i].kind == "heading":
            i += 1
            continue
        j = i
        while j < len(blocks) and blocks[j].id not in shown and blocks[j].kind != "heading":
            j += 1
        runs.append((i, j))
        i = j
    near = [k for k, b in enumerate(blocks) if b.id in shown] or [0]
    runs.sort(key=lambda r: -min(min(abs(r[0] - k), abs(r[1] - 1 - k)) for k in near))
    folded: dict[int, tuple[int, int]] = {}
    for a, b in runs:
        folded[a] = (a, b)
        if cost(_fold(entries, blocks, folded)) <= limit:
            break
    out = _fold(entries, blocks, folded)
    # still over: outline entries go, the last ones first (shown blocks always stay)
    keep = [t.startswith(tuple(f"[{s}] " for s in shown)) for t, _ in out]
    k = len(out) - 1
    while cost(out) > limit and k >= 0:
        if not keep[k]:
            out.pop(k)
            keep.pop(k)
        k -= 1
    return out


def _fold(
    entries: list[tuple[Block, str]], blocks: Sequence[Block], folded: dict[int, tuple[int, int]]
) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    skip = -1
    for k, (b, text) in enumerate(entries):
        if k < skip:
            continue
        if k in folded:
            a, z = folded[k]
            n = z - a
            first, last = blocks[a].id, blocks[z - 1].id
            where = f' under "{b.path[-1]}"' if b.path else ""
            span = first if n == 1 else f"{first}–{last}"
            out.append((f"[{span}] {n} block{'s' if n > 1 else ''}{where}", n))
            skip = z
            continue
        out.append((text, 0))
    return out


def vault_view(hits: Sequence[tuple[str, str, str]], budget: int) -> str:
    """Other notes' best sections (``(path, heading, text)``), labelled ``[V1]``…, cut to fit."""
    if not hits:
        return ""
    each = max(40, budget // len(hits))
    parts = []
    for n, (path, heading, text) in enumerate(hits, 1):
        where = f"{path} § {heading}" if heading else path
        parts.append(f"[V{n}] {where}\n{cut_to_tokens(text.strip(), each)}")
    return "\n\n".join(parts)
