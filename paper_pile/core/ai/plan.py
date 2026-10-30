"""The plan of an AI edit (PLAN §4.29, ``docs/AI_EDITS.md`` §4.4): which blocks change, which
get new text after / before them, and why — asked of the model as JSON whose block ids can only
be ids that exist (an ``enum`` in the schema), then checked and *snapped* here: a new section goes
to a section's end at its siblings' heading level, new text never lands between a heading and
its first paragraph. When the model gives no usable plan, a plan is made without it. Pure; no
UI imports.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from paper_pile.core.ai.blocks import Block
from paper_pile.core.ai.edit_context import key_terms

Action = Literal["change", "add_after", "add_before", "delete"]
ACTIONS: tuple[Action, ...] = ("change", "add_after", "add_before", "delete")
MAX_EDITS = 6
MAX_ALREADY = 3

PLAN_RULES = """Plan the edit. Do not write the new text yet.
Rules:
- Change as few blocks as possible, but every block that must change so the note stays
  consistent: lists, tables, counts ("three options"), summaries, introductions, tables of
  contents.
- If what the task adds is already in the note, do not add it again. Put that block in
  "already_there". If it is incomplete, add a "change" for that block instead.
- New content goes where a careful editor would put it: in the section it belongs to, after the
  last related block, in the note's own order. Add after a list item or table to extend that
  list or table.
- Set "new_section" to true only when the task asks for a new section or heading.
- "why" is a short phrase for the user, like "add the option to the table" or "update the count
  in the intro".
- If the task is unclear, write one short question in "question" and leave "edits" empty.
Answer with JSON only, matching this schema: """


@dataclass(frozen=True, slots=True)
class PlannedEdit:
    why: str
    action: Action
    block: str  # the block it changes, or the one new text goes after / before
    last: str = ""  # a change over several blocks ends with this one ("" = ``block``)
    new_section: bool = False
    level: int = 0  # the new section's heading level (after snapping)
    outside: bool = False  # not in the user's selection


@dataclass(frozen=True, slots=True)
class Plan:
    edits: tuple[PlannedEdit, ...]
    already: tuple[tuple[str, str], ...] = ()  # (block or vault id, "all" / "part")
    question: str = ""
    made_by_model: bool = True
    note: str = ""  # for the proposal's bar ("Changed only the selected text; …")


def plan_schema(ids: Sequence[str], vault_ids: Sequence[str] = ()) -> dict[str, Any]:
    """The JSON schema of a plan; ``ids``: the blocks it may name (not the fixed ones)."""
    named = list(ids) or ["B1"]
    return {
        "type": "object",
        "properties": {
            "already_there": {
                "type": "array",
                "maxItems": MAX_ALREADY,
                "items": {
                    "type": "object",
                    "properties": {
                        "block": {"enum": [*named, *vault_ids]},
                        "amount": {"enum": ["all", "part"]},
                    },
                    "required": ["block", "amount"],
                },
            },
            "edits": {
                "type": "array",
                "maxItems": MAX_EDITS,
                "items": {
                    "type": "object",
                    "properties": {
                        "why": {"type": "string", "maxLength": 80},
                        "action": {"enum": list(ACTIONS)},
                        "block": {"enum": named},
                        "new_section": {"type": "boolean"},
                    },
                    "required": ["why", "action", "block", "new_section"],
                },
            },
            "question": {"type": "string", "maxLength": 160},
        },
        "required": ["already_there", "edits", "question"],
    }


def plan_task(instruction: str, targets: Sequence[str], schema: dict[str, Any]) -> str:
    """The plan call's last message (the note view goes before it, shared with the writes)."""
    if not targets:
        where = "The user selected nothing (the whole note)."
    elif len(targets) == 1:
        where = f"The user selected block {targets[0]}."
    else:
        where = f"The user selected blocks {targets[0]}–{targets[-1]}."
    compact = json.dumps(schema, separators=(",", ":"))
    return f"Task: {instruction.strip()}\n{where}\n\n{PLAN_RULES}{compact}"


def parse_plan(
    data: dict[str, Any] | None,
    blocks: Sequence[Block],
    targets: Sequence[str],
    vault_ids: Sequence[str] = (),
) -> Plan | None:
    """The model's plan, checked: unknown ids, actions and fixed blocks dropped, at most
    ``MAX_EDITS``, one change per block. None when nothing usable is left (no edits, nothing
    already there, no question)."""
    if not isinstance(data, dict):
        return None
    by_id = {b.id: b for b in blocks}
    editable = {i for i, b in by_id.items() if not b.fixed}
    target_set = set(targets)
    edits: list[PlannedEdit] = []
    changed: set[str] = set()
    for raw in data.get("edits") or []:
        if not isinstance(raw, dict):
            continue
        action, block = raw.get("action"), raw.get("block")
        if action not in ACTIONS or not isinstance(block, str):
            continue
        if block not in editable and not (action.startswith("add") and block in by_id):
            continue  # new text may go next to a fixed block; a fixed block never changes
        if action in ("change", "delete"):
            if block in changed:
                continue
            changed.add(block)
        why = str(raw.get("why") or "").strip()[:80]
        outside = bool(target_set) and block not in target_set
        edits.append(
            PlannedEdit(
                why, action, block, new_section=bool(raw.get("new_section")), outside=outside
            )
        )
        if len(edits) == MAX_EDITS:
            break
    already: list[tuple[str, str]] = []
    for raw in data.get("already_there") or []:
        if isinstance(raw, dict) and raw.get("amount") in ("all", "part"):
            block = raw.get("block")
            if isinstance(block, str) and (block in by_id or block in vault_ids):
                already.append((block, str(raw["amount"])))
    question = str(data.get("question") or "").strip()[:160]
    if not edits and not already and not question:
        return None
    return Plan(tuple(edits), tuple(already[:MAX_ALREADY]), question)


def snap(plan: Plan, blocks: Sequence[Block]) -> Plan:
    """``plan`` with every insert moved to a legal place (see the module docstring)."""
    return replace(plan, edits=tuple(_snap_one(e, blocks) for e in plan.edits))


def _snap_one(edit: PlannedEdit, blocks: Sequence[Block]) -> PlannedEdit:
    if not edit.action.startswith("add"):
        return edit
    index = {b.id: i for i, b in enumerate(blocks)}
    at = index.get(edit.block)
    if at is None:
        return edit
    anchor = blocks[at]
    if edit.new_section:
        if edit.action == "add_before" and anchor.kind == "heading":
            return replace(edit, level=anchor.level)
        level = _section_level(blocks, at)
        end = _section_end(blocks, at, level)
        return replace(edit, action="add_after", block=blocks[end].id, level=level)
    if anchor.kind == "heading" and edit.action == "add_after":
        # never between a heading and its first paragraph: after the section's own text
        end = at
        while end + 1 < len(blocks) and blocks[end + 1].kind != "heading":
            end += 1
        return replace(edit, block=blocks[end].id)
    if anchor.kind == "front_matter":
        nxt = at + 1 if at + 1 < len(blocks) else at
        return replace(
            edit, action="add_before" if nxt != at else "add_after", block=blocks[nxt].id
        )
    return edit


def _section_level(blocks: Sequence[Block], at: int) -> int:
    """The heading level a new section next to block ``at`` gets: that of the section it is in;
    with no heading above it, 2 (1 when every heading of the note is level 1)."""
    titles = sum(1 for b in blocks if b.kind == "heading" and b.level == 1)
    level = 0
    if blocks[at].kind == "heading":
        level = blocks[at].level
    else:
        level = next((b.level for b in reversed(blocks[:at]) if b.kind == "heading"), 0)
    if level == 1 and titles == 1:
        return 2  # the note's one title: a new section goes under it, never beside it
    if level:
        return level
    levels = {b.level for b in blocks if b.kind == "heading"}
    return 1 if levels == {1} and titles > 1 else 2


def _section_end(blocks: Sequence[Block], at: int, level: int) -> int:
    """The last block of the section (of ``level``) holding block ``at``."""
    end = at
    while end + 1 < len(blocks):
        nxt = blocks[end + 1]
        if nxt.kind == "heading" and nxt.level <= level:
            break
        end += 1
    return end


def fallback_plan(
    blocks: Sequence[Block],
    note: str,
    targets: Sequence[str],
    instruction: str,
    *,
    adds: bool,
) -> Plan:
    """A plan made without the model: with a selection, one change of it; with none and a task
    that adds content, new text after the section it fits best (by shared words; else the end
    of the note); otherwise a change of the whole body."""
    if targets:
        note_text = "Changed only the selected text; the AI could not plan other places."
        edit = PlannedEdit("the selected text", "change", targets[0], last=targets[-1])
        return Plan((edit,), made_by_model=False, note=note_text)
    body = [b for b in blocks if b.kind != "front_matter"]
    if not body:
        return Plan((), made_by_model=False)
    if not adds:
        return Plan(
            (PlannedEdit("the note", "change", body[0].id, last=body[-1].id),),
            made_by_model=False,
        )
    terms = key_terms(instruction)
    best, score = body[-1], (0, 0)
    for i, b in enumerate(blocks):
        if b.kind != "heading":
            continue
        end = _section_end(blocks, i, b.level)
        words = " ".join(x.text(note) for x in blocks[i : end + 1]).lower()
        hits = (sum(1 for t in terms if t in words), i - end)  # on a tie: the smaller section
        if hits[0] and hits > score:
            best, score = blocks[end], hits
    return Plan((PlannedEdit("the new text", "add_after", best.id),), made_by_model=False)
