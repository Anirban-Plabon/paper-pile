"""P26.4: the plan of an AI edit — schema, checks, snapping, fallback (PLAN §4.29)."""

from paper_pile.core.ai.blocks import block_map
from paper_pile.core.ai.plan import (
    Plan,
    PlannedEdit,
    fallback_plan,
    parse_plan,
    plan_schema,
    plan_task,
    snap,
)

NOTE = """---
title: Guide
---
# Guide

Intro text.

## Setup

Install it.

## Usage

Run it.

### Flags

Use --fast.

## Maintenance

Update it monthly.

## FAQ

Ask us.
"""
BLOCKS = block_map(NOTE)
ID = {b.text(NOTE).split("\n")[0]: b.id for b in BLOCKS}


def test_schema_names_only_real_editable_blocks() -> None:
    ids = [b.id for b in BLOCKS if not b.fixed]
    schema = plan_schema(ids, ["V1"])
    edit = schema["properties"]["edits"]["items"]["properties"]
    assert edit["block"]["enum"] == ids and "B0" not in ids
    assert schema["properties"]["already_there"]["items"]["properties"]["block"]["enum"][-1] == "V1"
    task = plan_task("add backups", [], schema)
    assert task.startswith("Task: add backups\nThe user selected nothing (the whole note).")
    assert task.endswith('"required":["already_there","edits","question"]}')
    assert "blocks B3–B5" in plan_task("x", ["B3", "B4", "B5"], schema)


def test_parse_drops_what_is_not_usable() -> None:
    data = {
        "already_there": [{"block": "B99", "amount": "all"}, {"block": "B2", "amount": "part"}],
        "edits": [
            {"why": "a", "action": "change", "block": "B2", "new_section": False},
            {"why": "again", "action": "change", "block": "B2", "new_section": False},
            {"why": "bad", "action": "explode", "block": "B2", "new_section": False},
            {"why": "nope", "action": "change", "block": "B0", "new_section": False},
            {"why": "unknown", "action": "change", "block": "B77", "new_section": False},
            {"why": "x" * 200, "action": "add_after", "block": "B4", "new_section": False},
        ],
        "question": "",
    }
    plan = parse_plan(data, BLOCKS, ["B2"])
    assert plan is not None
    assert [(e.action, e.block) for e in plan.edits] == [("change", "B2"), ("add_after", "B4")]
    assert len(plan.edits[1].why) == 80 and plan.edits[1].outside and not plan.edits[0].outside
    assert plan.already == (("B2", "part"),)
    assert parse_plan({"edits": [], "already_there": [], "question": ""}, BLOCKS, []) is None
    assert parse_plan(None, BLOCKS, []) is None
    asked = parse_plan({"edits": [], "question": "Which section?"}, BLOCKS, [])
    assert asked is not None and asked.question == "Which section?"


def new_section(anchor: str) -> PlannedEdit:
    data = {"edits": [{"why": "w", "action": "add_after", "block": anchor, "new_section": True}]}
    plan = parse_plan(data, BLOCKS, [])
    assert plan is not None
    return snap(plan, BLOCKS).edits[0]


def test_a_new_section_goes_to_a_section_end_at_the_siblings_level() -> None:
    edit = new_section(ID["Update it monthly."])
    assert (edit.action, edit.block, edit.level) == ("add_after", ID["Update it monthly."], 2)
    # anchored on a heading with sub-sections: after the whole section, not inside it
    usage = new_section(ID["## Usage"])
    assert usage.block == ID["Use --fast."] and usage.level == 2
    # next to the intro under the one "# Guide" title: a level-2 section, not a second title
    intro = new_section(ID["Intro text."])
    assert intro.level == 2 and intro.block == ID["Intro text."]


def test_text_never_goes_between_a_heading_and_its_first_paragraph() -> None:
    plan = snap(Plan((PlannedEdit("w", "add_after", ID["## Usage"]),)), BLOCKS)
    assert plan.edits[0].block == ID["Run it."]  # the section's own text, before "### Flags"


def test_fallbacks() -> None:
    sel = fallback_plan(BLOCKS, NOTE, ["B3", "B4"], "make it formal", adds=False)
    assert not sel.made_by_model and sel.note.startswith("Changed only the selected text")
    assert [(e.action, e.block, e.last) for e in sel.edits] == [("change", "B3", "B4")]
    add = fallback_plan(BLOCKS, NOTE, [], "add a note about monthly updates", adds=True)
    assert add.edits[0].action == "add_after" and add.edits[0].block == ID["Update it monthly."]
    whole = fallback_plan(BLOCKS, NOTE, [], "make it formal", adds=False)
    assert whole.edits[0].block == ID["# Guide"] and whole.edits[0].last == ID["Ask us."]


def test_options_only_when_asked_for() -> None:
    ids = [b.id for b in BLOCKS if not b.fixed]
    plain = plan_schema(ids)
    assert "options" not in plain["properties"] and '"options"' not in plan_task("x", [], plain)
    offered = plan_schema(ids, options=True)
    assert offered["required"] == ["already_there", "edits", "options", "question"]
    task = plan_task("x", [], offered)
    assert task.index('in "options"') < task.index("If the task is unclear")


def test_parse_options() -> None:
    raw = {"edits": [], "options": ["Add a FAQ entry", "  add a faq ENTRY ", 3, "", "b", "c", "d"]}
    found = parse_plan(raw, BLOCKS, [])
    assert found is not None and found.options == ("Add a FAQ entry", "b", "c", "d")
    assert parse_plan({"edits": [], "options": "nope"}, BLOCKS, []) is None
