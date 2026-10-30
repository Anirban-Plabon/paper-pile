"""P26.5: writing one planned change and fitting the answer into the note (PLAN §4.29)."""

from paper_pile.core.ai.blocks import block_map
from paper_pile.core.ai.plan import PlannedEdit
from paper_pile.core.ai.write import delete_change, fit_answer, write_job
from paper_pile.core.tables import format_table, parse_table

NOTE = """# Hosting

We compare three options. See [[Plan]] and run `make up`.

```sh
make up
```

- **Docker**: one container
- **VM**: a whole machine

1. first
2. second

| Name | Price |
|---|---|
| Docker | 0 |

## Next
"""
BLOCKS = block_map(NOTE)
ID = {b.text(NOTE).split("\n")[0]: b.id for b in BLOCKS}


def apply(change) -> str:  # type: ignore[no-untyped-def]
    return NOTE[: change.start] + change.new + NOTE[change.end :]


def test_change_job_masks_code_and_names_tokens() -> None:
    edit = PlannedEdit(
        "tidy the intro",
        "change",
        ID["We compare three options. See [[Plan]] and run `make up`."],
        last=ID["```sh"],
    )
    job = write_job(edit, BLOCKS, NOTE, "make it formal", earlier=["- **Fly.io**: hosted"])
    assert "<<<\nWe compare three options." in job.task and "⟦KEEP 1⟧\n>>>" in job.task
    assert "make up\n```" not in job.task.split("<<<")[1]  # the code block is set aside
    assert "Keep exactly: [[Plan]], `make up`" in job.task
    assert "Where it is (context, do not write it): Hosting" in job.task
    assert "Before it (context, do not write it):\n# Hosting" in job.task
    assert "Already written for this task (context, do not write it):\n- **Fly.io**" in job.task
    assert job.task.endswith(f"Reply with the new text for [{edit.block}–{edit.last}] only.")
    new = "We weigh three options. See [[Plan]] and run `make up`.\n\n⟦KEEP 1⟧\n"
    change = fit_answer(job, BLOCKS, NOTE, new)
    assert change is not None
    assert apply(change).startswith(
        "# Hosting\n\nWe weigh three options. See [[Plan]] and run `make up`."
        "\n\n```sh\nmake up\n```\n\n- **Docker**"
    )
    assert fit_answer(job, BLOCKS, NOTE, "We weigh three options.") is None  # code block lost


def test_new_items_take_the_lists_marker() -> None:
    edit = PlannedEdit("add the option", "add_after", ID["- **VM**: a whole machine"])
    job = write_job(edit, BLOCKS, NOTE, "add Fly.io")
    assert "Start each with `- ` like its items" in job.task
    change = fit_answer(job, BLOCKS, NOTE, "* **Fly.io**: hosted\n  runs anywhere\nBare metal")
    assert change is not None
    expected = (
        "- **VM**: a whole machine\n- **Fly.io**: hosted\n  runs anywhere\n- Bare metal\n\n1."
    )
    assert expected in apply(change)
    numbered = PlannedEdit("w", "add_after", ID["2. second"])
    change = fit_answer(write_job(numbered, BLOCKS, NOTE, "x"), BLOCKS, NOTE, "- third\n- fourth")
    assert change is not None and "2. second\n3. third\n4. fourth\n\n| Name" in apply(change)
    plain = fit_answer(write_job(edit, BLOCKS, NOTE, "x"), BLOCKS, NOTE, "[ ] check it")
    assert plain is not None and "\n- [ ] check it\n" in apply(plain)


def test_new_rows_fit_the_table() -> None:
    edit = PlannedEdit("add to the table", "add_after", ID["| Name | Price |"])
    job = write_job(edit, BLOCKS, NOTE, "add Fly.io")
    assert (
        "Each row has exactly 2 cells" in job.task
        and "The header is: `| Name | Price |`" in job.task
    )
    answer = "| Name | Price |\n|---|---|\n| Fly.io | 2 |\n| Bare | 9 | extra |"
    change = fit_answer(job, BLOCKS, NOTE, answer)
    assert change is not None
    assert "| Docker | 0 |\n| Fly.io | 2 |\n| Bare | 9 |\n\n## Next" in apply(change)
    assert [i.kind for i in change.issues] == ["cells"]
    aligned_note = "| Name   | Price |\n| ------ | ----- |\n| Docker | 0     |\n"
    table = parse_table(aligned_note.strip())
    assert table is not None and format_table(table) == aligned_note.strip()
    blocks = block_map(aligned_note)
    job = write_job(PlannedEdit("w", "add_after", blocks[0].id), blocks, aligned_note, "x")
    grown = fit_answer(job, blocks, aligned_note, "| Fly.io | 2 |")
    assert grown is not None and grown.new.split("\n")[-1] == "| Fly.io | 2     |"


def test_new_section_and_paragraphs() -> None:
    edit = PlannedEdit(
        "add backups", "add_after", ID["| Name | Price |"], new_section=True, level=2
    )
    job = write_job(edit, BLOCKS, NOTE, "add a section about backups")
    assert "Start with one heading line at level 2 (`## `)" in job.task
    change = fit_answer(job, BLOCKS, NOTE, "### Backups\n\nCopy it nightly.")
    assert (
        change is not None
        and "| Docker | 0 |\n\n## Backups\n\nCopy it nightly.\n\n## Next" in apply(change)
    )
    assert [i.severity for i in change.issues] == ["fixed"]
    before = PlannedEdit("w", "add_before", ID["## Next"])
    para = fit_answer(write_job(before, BLOCKS, NOTE, "x"), BLOCKS, NOTE, "\nA paragraph.\n")
    assert para is not None and "| Docker | 0 |\n\nA paragraph.\n\n## Next" in apply(para)
    assert fit_answer(write_job(before, BLOCKS, NOTE, "x"), BLOCKS, NOTE, "  \n") is None


def test_delete_takes_the_blank_lines_along() -> None:
    gone = delete_change(
        PlannedEdit("w", "delete", ID["1. first"], last=ID["2. second"]), BLOCKS, NOTE
    )
    assert "- **VM**: a whole machine\n\n| Name" in apply(gone)
    last = delete_change(PlannedEdit("w", "delete", ID["## Next"]), BLOCKS, NOTE)
    assert apply(last).endswith("| Docker | 0 |\n")
