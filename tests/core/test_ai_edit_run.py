"""P26.9: one AI change from request to proposal, with scripted model answers (PLAN §4.29)."""

import json
from pathlib import Path

import pytest

from paper_pile.core.ai.access import AccessDeniedError
from paper_pile.core.ai.blocks import block_map
from paper_pile.core.ai.edit_run import EditResult, EditRun
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.proposals import accept, apply_changes
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault

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
| Bare metal | 40 |

## Notes

Teh backups runs every night. See [[Ops]].
"""
ID = {b.text(NOTE).split("\n")[0]: b.id for b in block_map(NOTE)}
BACKUPS = "Teh backups runs every night. See [[Ops]]."
LAST_ITEM = ID["- **Bare metal**: no layer"]
TABLE = ID["| Option | Price |"]
INTRO = ID["We compare three options for hosting."]
DOCKER = ID["- **Docker**: one container"]


def make(tmp_path: Path, script: list[str]) -> tuple[AiEngine, FakeProvider]:
    root = tmp_path / "v"
    root.mkdir(parents=True)
    (root / "h.md").write_text(NOTE)
    fake = FakeProvider(delay=0, script=script)
    vault, config = Vault(root), Config(vault=root)
    ai = AiEngine(vault, config, user_name=lambda: "Ana", provider_factory=lambda _c: fake)
    ai.allow()
    return ai, fake


def run_on(
    ai: AiEngine, selection: tuple[int, int] | None, instruction: str, **kw: object
) -> EditRun:
    return EditRun(
        ai,
        path="h.md",
        note=NOTE,
        selection=selection,
        instruction=instruction,
        **kw,  # type: ignore[arg-type]
    )


def step(why: str, action: str, block: str) -> dict[str, object]:
    return {"why": why, "action": action, "block": block, "new_section": False}


def plan(*edits: dict[str, object], already: list[object] | None = None, question: str = "") -> str:
    return json.dumps({"already_there": already or [], "edits": list(edits), "question": question})


def final(result: EditResult) -> str:
    assert result.proposal is not None
    done = accept(result.proposal, NOTE)
    assert done is not None
    return apply_changes(NOTE, done[0])


def sel(text: str) -> tuple[int, int]:
    at = NOTE.index(text)
    return at, at + len(text)


async def test_a_selection_fix_is_one_call_and_a_title_is_not_injected(tmp_path: Path) -> None:
    ai, fake = make(tmp_path, ["## Backups\n\nThe backups run every night. See [[Ops]]."])
    result = await run_on(ai, sel(BACKUPS), "fix grammar").run()
    assert result.calls == 1 and len(fake.calls) == 1
    assert "The backups run every night. See [[Ops]]." in final(result)
    assert "## Backups" not in final(result)
    (change,) = result.changes
    assert [i.kind for i in change.issues] == ["heading"] and result.clean
    sent = fake.options_seen[0]
    assert sent is not None and sent.think is False and sent.temperature == 0.3


async def test_adding_an_option_changes_every_place(tmp_path: Path) -> None:
    planned = plan(
        step("add the option", "add_after", LAST_ITEM),
        step("add it to the table", "add_after", TABLE),
        step("update the count", "change", INTRO),
    )
    script = [
        planned,
        "- **Fly.io**: a hosted platform",
        "| Fly.io | 2 |",
        "We compare four options for hosting.",
    ]
    ai, fake = make(tmp_path, script)
    progress: list[str] = []
    result = await run_on(ai, None, "add option D: Fly.io", on_progress=progress.append).run()
    first = fake.options_seen[0]
    assert result.calls == 4 and first is not None and first.schema is not None
    text = final(result)
    assert "- **Bare metal**: no layer\n- **Fly.io**: a hosted platform\n\n## Cost" in text
    assert "| Bare metal | 40 |\n| Fly.io | 2 |\n\n## Notes" in text
    assert "We compare four options for hosting." in text
    assert result.proposal is not None and len(result.proposal.regions) == 3
    reasons = [h.reason for h in result.proposal.hunks]
    assert reasons == ["update the count", "add the option", "add it to the table"]
    assert progress[:2] == ["Planning…", "Writing 1 of 3…"] and progress[-1] == "Checking…"
    # the writes share the plan's start (the note as blocks), and each sees what came before
    assert fake.calls[1][:2] == fake.calls[0][:2]
    assert "Already written for this task" in fake.calls[2][-1].content


async def test_a_bad_plan_twice_falls_back(tmp_path: Path) -> None:
    bad = '{"edits": [{"block": "B999"}]}'
    ai, _ = make(tmp_path, ["not json", bad, "Backups are kept for a month."])
    result = await run_on(ai, None, "add a note that backups are kept a month").run()
    assert result.calls == 3
    assert BACKUPS + "\n\nBackups are kept for a month." in final(result)


async def test_question_and_already_there(tmp_path: Path) -> None:
    ai, _ = make(tmp_path, [plan(question="Which option?")])
    result = await run_on(ai, None, "add the missing one").run()
    assert result.question == "Which option?" and result.proposal is None
    ai, _ = make(tmp_path / "b", [plan(already=[{"block": DOCKER, "amount": "all"}])])
    result = await run_on(ai, None, "add Docker as an option").run()
    said = "This is already in the note: “- **Docker**: one container” (Hosting, line 5)."
    assert result.already == said


async def test_a_dropped_link_is_asked_for_again(tmp_path: Path) -> None:
    fixed = "The backups run every night."
    ai, fake = make(tmp_path, [fixed, fixed + " See [[Ops]]."])
    result = await run_on(ai, sel(BACKUPS), "fix grammar").run()
    assert result.calls == 2 and "You dropped [[Ops]]" in fake.calls[1][-1].content
    assert result.clean and "See [[Ops]]." in final(result)
    ai, _ = make(tmp_path / "b", ["The backups run.", "Still no link."])
    result = await run_on(ai, sel(BACKUPS), "fix grammar").run()
    assert not result.clean  # a warning: never applied unseen
    assert any(i.kind == "tokens" and i.severity == "warn" for i in result.changes[0].issues)


async def test_a_failure_keeps_what_was_finished(tmp_path: Path) -> None:
    two = plan(step("a", "add_after", LAST_ITEM), step("b", "add_after", TABLE))
    ai, _ = make(tmp_path, [two, "- **Fly.io**: hosted"])  # the 3rd call fails
    result = await run_on(ai, None, "add option Fly.io").run()
    assert result.error and len(result.changes) == 1 and "Fly.io" in final(result)


async def test_maybe_also_update(tmp_path: Path) -> None:
    one = plan(step("add", "add_after", LAST_ITEM))
    ai, _ = make(tmp_path, [one, "- **Fly.io**: hosted", "| Fly.io | 2 |"])
    run = run_on(ai, None, "add option Fly.io")
    result = await run.run()
    assert {TABLE, INTRO} <= {s.block for s in result.suggestions}
    assert result.proposal is not None
    assert any(n.kind == "maybe-update" for n in result.proposal.notes)
    table = next(s for s in result.suggestions if s.block == TABLE)
    assert table.action == "add_after"
    more = await run.update(table)
    assert "| Bare metal | 40 |\n| Fly.io | 2 |" in final(more)


async def test_a_private_note_is_never_sent(tmp_path: Path) -> None:
    ai, fake = make(tmp_path, ["x"])
    private = "---\nai: false\n---\nSecret.\n"
    with pytest.raises(AccessDeniedError):
        await EditRun(ai, path="h.md", note=private, selection=None, instruction="x").run()
    assert fake.calls == []
