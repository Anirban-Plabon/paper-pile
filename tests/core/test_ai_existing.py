"""P26.7: content that is already there, and other places to update (PLAN §4.29)."""

from paper_pile.core.ai.blocks import block_map
from paper_pile.core.ai.consistency import suggestions
from paper_pile.core.ai.existing import containment, existing_answer, in_note, in_vault, pieces
from paper_pile.core.ai.write import PlannedChange

NOTE = """# Hosting

We compare three options for hosting.

- **Docker**: one container
- **VM**: a whole machine
- **Bare metal**: no layer

## Cost

| Option | Price |
|---|---|
| Docker | 0 |
| VM | 5 |

## Notes

Backups run every night to the cloud bucket we pay for.
"""
BLOCKS = block_map(NOTE)
ID = {b.text(NOTE).split("\n")[0]: b.id for b in BLOCKS}


def test_pieces_and_containment() -> None:
    assert pieces("- a\n  more\n- b") == ["- a\n  more", "- b"]
    assert pieces("| x | 1 |\n|---|---|\n| y | 2 |") == ["| x | 1 |", "| y | 2 |"]
    assert pieces("One.\n\nTwo.") == ["One.", "Two."]
    assert containment("backups run every night", "Backups run every night to the cloud") == 1.0
    assert containment("ok", "anything") == 0.0  # too short to compare by 3-grams


def test_an_item_that_is_already_in_the_list() -> None:
    found = in_note("- **Docker**: containers\n- **Fly.io**: hosted", BLOCKS, NOTE)
    assert [(i.kind, i.data) for i in found] == [("exists", ID["- **Docker**: one container"])]
    assert found[0].message == "May repeat line 5 (Hosting)"
    assert in_note("| VM | 7 |", BLOCKS, NOTE)[0].data == ID["| Option | Price |"]
    para = in_note("Backups run every night to the cloud bucket.", BLOCKS, NOTE)
    assert para[0].message == "May repeat line 18 (Notes)"
    assert in_note("Something entirely new here today.", BLOCKS, NOTE) == []
    skip = [ID["- **Docker**: one container"]]
    assert in_note("- **Docker**: x", BLOCKS, NOTE, skip=skip)[0].data == ID["| Option | Price |"]


def test_similar_text_in_another_note_is_only_told() -> None:
    hits = [("ops/backup.md", "Schedule", "Backups run every night to the cloud bucket.")]
    (issue,) = in_vault("Backups run every night to the cloud.", hits)
    assert issue.severity == "info" and issue.message == "Similar text in [[ops/backup#Schedule]]"
    assert in_vault("Unrelated words go here now.", hits) == []


def test_an_answer_the_note_already_has() -> None:
    note = "# Plan\n\n**Summary**: short.\n\nBody text.\n"
    blocks = block_map(note)
    issue = existing_answer("ai-summarize", blocks, note, blocks[-1].id)
    assert issue is not None and issue.message == "This note already has a Summary (line 3)"
    assert existing_answer("ai-explain", blocks, note, blocks[-1].id) is None


def test_adding_an_item_suggests_the_table_and_the_count() -> None:
    last = next(b for b in BLOCKS if b.text(NOTE).startswith("- **Bare metal**"))
    change = PlannedChange(last.end, last.end, "\n- **Fly.io**: hosted")
    found = {s.block: s.why for s in suggestions(BLOCKS, NOTE, [change])}
    assert found == {
        ID["| Option | Price |"]: 'The table under "Cost" lists the same items but not “fly.io”',
        ID["We compare three options for hosting."]: "It says “three options” (now 4)",
    }
    table = BLOCKS[[b.id for b in BLOCKS].index(ID["| Option | Price |"])]
    both = [change, PlannedChange(table.end, table.end, "\n| Fly.io | 2 |")]
    assert ID["| Option | Price |"] not in {s.block for s in suggestions(BLOCKS, NOTE, both)}
