"""After an AI edit: other places that may need the same change (PLAN §4.29,
``docs/AI_EDITS.md`` §4.8), found without the model, for any list or table:

* a list or table that describes the same things (shares at least two item keys, half of its
  own) but lacks what was just added — "The table under ## Cost lists the same items but not
  “Fly.io”";
* a number that counted the grown list or table — "We compare **three** options" next to a
  word from its heading or the line before it.

Each is offered as "Maybe also update: … [Update]"; nothing is changed by itself. Pure; no UI
imports.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from paper_pile.core.ai.blocks import Block
from paper_pile.core.ai.edit_context import NUMBER_WORDS, item_key, stem, structure_keys
from paper_pile.core.ai.existing import pieces
from paper_pile.core.ai.write import PlannedChange

_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True, slots=True)
class Suggestion:
    block: str  # the block to update
    why: str  # shown to the user, and the model's "This change:" if they click Update


@dataclass(frozen=True, slots=True)
class _Structure:
    ids: tuple[str, ...]
    keys: tuple[str, ...]
    label: str  # 'the table under "Cost"'
    terms: frozenset[str]  # words of its heading and the line before it


def _structures(blocks: Sequence[Block], note: str) -> list[_Structure]:
    out: list[_Structure] = []
    lists: dict[str, list[Block]] = {}
    for b in blocks:
        if b.kind == "item":
            lists.setdefault(b.list_id, []).append(b)
        elif b.kind == "table":
            out.append(_structure([b], "table", blocks, note))
    out.extend(_structure(items, "list", blocks, note) for items in lists.values())
    return out


def _structure(items: list[Block], kind: str, blocks: Sequence[Block], note: str) -> _Structure:
    keys = tuple(k for b in items for k in structure_keys(b, note))
    first = items[0]
    under = f' under "{first.path[-1]}"' if first.path else ""
    index = [b.id for b in blocks].index(first.id)
    lead = blocks[index - 1].text(note) if index > 0 else ""
    words = " ".join([*first.path[-1:], lead])
    terms = frozenset(stem(w) for w in _WORD.findall(words) if len(w) > 2)
    return _Structure(tuple(b.id for b in items), keys, f"the {kind}{under}", terms)


def _number_words(n: int) -> set[str]:
    out = {str(n)}
    if 1 <= n <= len(NUMBER_WORDS):
        out.add(NUMBER_WORDS[n - 1])
    return out


def suggestions(
    blocks: Sequence[Block], note: str, changes: Sequence[PlannedChange]
) -> list[Suggestion]:
    """What else may need updating after ``changes`` (made to ``note``, whose blocks are
    ``blocks``)."""
    touched = {
        b.id
        for b in blocks
        for c in changes
        if c.start < b.end and b.start < c.end or b.start <= c.start <= b.end
    }
    structures = _structures(blocks, note)
    out: list[Suggestion] = []
    seen: set[str] = set()
    for grown in structures:
        if not touched & set(grown.ids):
            continue
        span = (_by_id(blocks, grown.ids[0]).start, _by_id(blocks, grown.ids[-1]).end)
        mine = [c for c in changes if span[0] <= c.start <= span[1]]
        added = [
            key
            for c in mine
            for key in (item_key(p) for p in pieces(c.new))
            if key and key not in grown.keys
        ]
        if not added:
            continue
        old = set(grown.keys)
        for other in structures:
            if other is grown or touched & set(other.ids) or other.ids[-1] in seen:
                continue
            shared = old & set(other.keys)
            if len(shared) >= 2 and len(shared) * 2 >= len(set(other.keys)):
                missing = [k for k in added if k not in other.keys]
                if missing:
                    seen.add(other.ids[-1])
                    names = ", ".join(f"“{k}”" for k in missing)
                    out.append(
                        Suggestion(
                            other.ids[-1],
                            f"{other.label[0].upper()}{other.label[1:]} lists the same items "
                            f"but not {names}",
                        )
                    )
        out.extend(_counts(blocks, note, grown, len(old), len(old) + len(added), touched, seen))
    return out


def _by_id(blocks: Sequence[Block], block_id: str) -> Block:
    return next(b for b in blocks if b.id == block_id)


def _counts(
    blocks: Sequence[Block],
    note: str,
    grown: _Structure,
    before: int,
    after: int,
    touched: set[str],
    seen: set[str],
) -> list[Suggestion]:
    numbers = _number_words(before)
    out: list[Suggestion] = []
    for b in blocks:
        if b.id in touched or b.id in grown.ids or b.id in seen or b.fixed:
            continue
        if b.kind in ("item", "table"):
            continue
        words = _WORD.findall(b.text(note))
        for i, w in enumerate(words):
            if w.lower() not in numbers:
                continue
            near = {stem(x) for x in words[max(0, i - 3) : i + 4]}
            if near & grown.terms:
                phrase = " ".join(words[i : i + 2])
                seen.add(b.id)
                out.append(Suggestion(b.id, f"It says “{phrase}” (now {after})"))
                break
    return out
