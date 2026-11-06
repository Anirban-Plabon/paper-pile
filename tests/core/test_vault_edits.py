"""Vault agent M6: edits across notes and new notes (PLAN_vault_agent P30.29–P30.33) — the
target, the dry run, deterministic removal, review text, apply only what is picked, never over
a note that changed, undo, and the whole flow through ``AiEngine.answer`` with a scripted
backend."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from paper_pile.core.ai.context import EditorSnapshot
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.proposals import propose
from paper_pile.core.ai.provider import ChatMessage, ProviderError
from paper_pile.core.ai.vault import edits as edits_mod
from paper_pile.core.ai.vault.cite import make_sources, to_wikilinks
from paper_pile.core.ai.vault.edits import (
    EditBatch,
    NoteEdit,
    Target,
    VaultWriter,
    apply_batch,
    edit_target,
    free_note_path,
    propose_batch,
    review_text,
    skip_reason,
    undo,
)
from paper_pile.core.ai.vault.newnote import note_title
from paper_pile.core.ai.vault.session import review_answer
from paper_pile.core.config import Config
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault

ACME = "# Acme\n\nIntro.\n\n## Budget\n\n10k\n\n## Contacts\n\nJane\n"
BETA = "# Beta\n\nNo budget here.\n"


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path / "v")
    v.root.mkdir()
    v.create_note("Clients/Acme.md", ACME)
    v.create_note("Clients/Beta.md", BETA)
    return v


class Model:
    def __init__(self, target: dict[str, str] | Exception) -> None:
        self.target = target

    async def ask_json(self, msgs: Any, schema: Any, *, max_answer: int = 0) -> Any:
        assert schema is edits_mod.TARGET_SCHEMA
        if isinstance(self.target, Exception):
            raise self.target
        return self.target


# ---- target, dry run, removal ----------------------------------------------------------------


def test_edit_target() -> None:
    got = asyncio.run(
        edit_target(Model({"kind": "remove", "section": "## Budget ", "instruction": "x"}), "r")
    )  # type: ignore[arg-type]
    assert got == Target("remove", "Budget", "x")
    fallback = asyncio.run(edit_target(Model(ProviderError("down")), "add sources"))  # type: ignore[arg-type]
    assert fallback == Target("change", "", "add sources")


def test_skip_reason() -> None:
    assert skip_reason(Target("add", "Budget", "x"), ACME) == "already has a Budget section"
    assert skip_reason(Target("add", "Budget", "x"), BETA) == ""
    assert skip_reason(Target("remove", "budget", "x"), BETA) == "no budget section"
    assert skip_reason(Target("change", "Budget", "x"), ACME) == ""
    assert skip_reason(Target("remove", "", "x"), ACME) == "nothing to remove"


def test_remove_section_without_a_model(vault: Vault) -> None:
    writer = VaultWriter(vault)
    batch = asyncio.run(
        propose_batch(
            None,  # type: ignore[arg-type]  # no model call for a removal
            "remove the Budget sections",
            [("Clients/Acme.md", "Acme"), ("Clients/Beta.md", "Beta")],
            writer,
            target=Target("remove", "Budget", "remove it"),
        )
    )
    assert [e.path for e in batch.ready] == ["Clients/Acme.md"]
    assert batch.skipped == [("Beta", "no Budget section")]
    assert batch.ready[0].after == "# Acme\n\nIntro.\n\n## Contacts\n\nJane\n"
    text = review_text(batch)
    assert text.startswith("**1 note would change**, 1 left out")
    assert "- ## Budget" in text and "Left out: Beta (no Budget section)" in text
    assert vault.read_text("Clients/Acme.md") == ACME  # nothing written by proposing


# ---- apply / stale / undo --------------------------------------------------------------------


def batch_for(vault: Vault, path: str, before: str, after: str) -> EditBatch:
    proposal = propose(path, before, 0, len(before), after)
    batch = EditBatch("r", Target("change", "", "r"))
    batch.edits.append(NoteEdit(path, path, before, proposal))
    return batch


def test_apply_picks_and_undo(vault: Vault) -> None:
    writer = VaultWriter(vault)
    batch = batch_for(vault, "Clients/Acme.md", ACME, ACME + "\n## Sources\n")
    batch.edits += batch_for(vault, "Clients/Beta.md", BETA, BETA + "\nmore\n").edits
    done = apply_batch(batch, [2], writer)  # only the second note
    assert done.paths == ["Clients/Beta.md"] and vault.read_text("Clients/Acme.md") == ACME
    assert vault.read_text("Clients/Beta.md") == BETA + "\nmore\n"
    restored, kept = undo(done, writer)
    assert restored == ["Clients/Beta.md"] and kept == []
    assert vault.read_text("Clients/Beta.md") == BETA


def test_never_written_over_a_changed_note(vault: Vault) -> None:
    writer = VaultWriter(vault)
    batch = batch_for(vault, "Clients/Acme.md", ACME, "AI text\n")
    vault.write_text("Clients/Acme.md", ACME + "typed meanwhile\n")
    done = apply_batch(batch, None, writer)
    assert done.paths == [] and [e.path for e in done.stale] == ["Clients/Acme.md"]
    assert vault.read_text("Clients/Acme.md") == ACME + "typed meanwhile\n"


def test_undo_leaves_a_note_changed_again(vault: Vault) -> None:
    writer = VaultWriter(vault)
    done = apply_batch(batch_for(vault, "Clients/Acme.md", ACME, "AI\n"), None, writer)
    vault.write_text("Clients/Acme.md", "AI\nuser edit\n")
    restored, kept = undo(done, writer)
    assert restored == [] and kept == ["Clients/Acme.md"]
    assert vault.read_text("Clients/Acme.md") == "AI\nuser edit\n"


def test_new_note_never_replaces_one(vault: Vault) -> None:
    assert free_note_path(vault, "Clients/Overview") == "Clients/Overview.md"
    vault.create_note("Clients/Overview.md", "mine\n")
    assert free_note_path(vault, "Clients/Overview.md") == "Clients/Overview 1.md"
    batch = EditBatch("r", Target("add", "", "r"))
    batch.edits.append(
        NoteEdit("Clients/Overview.md", "Overview", "", propose("x", "", 0, 0, "# New\n"), new=True)
    )
    done = apply_batch(batch, None, VaultWriter(vault))
    assert done.created == ["Clients/Overview 1.md"]
    assert vault.read_text("Clients/Overview.md") == "mine\n"
    assert vault.read_text("Clients/Overview 1.md") == "# New\n"


def test_review_answer_and_helpers() -> None:
    assert review_answer("Apply all", 3) == "all" and review_answer(" cancel ", 3) == "cancel"
    assert review_answer("1, 3", 3) == [1, 3] and review_answer("2 9", 3) == [2]
    assert review_answer("9", 3) is None and review_answer("what about X?", 3) is None
    assert note_title('social: business/"ideas"') == "Social business ideas"
    assert note_title("") == "Summary"
    srcs = make_sources(
        [("R/Yunus.md", "Yunus", "", 1, 2, "t"), ("R/Bank.md", "Bank", "Plan", 3, 4, "u")]
    )
    assert to_wikilinks("A [1]. B [1, 2]. C [7].", srcs, lambda p: p[:-3]) == (
        "A ([[R/Yunus]]). B ([[R/Yunus]], [[R/Bank#Plan]]). C [7]."
    )


# ---- the whole flow through the chat -------------------------------------------------------------


def step(action: str, **kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "action": action,
        "meta": "",
        "folders": [],
        "tags": [],
        "notes": [],
        "linked_from": [],
        "links_to": [],
        "dates": {},
        "date_kind": "content",
        "from_result": "",
        "topic": "",
        "terms": [],
        "detail": "",
        "depends_on": -1,
    }
    base.update(kw)
    return base


def backend(msgs: list[ChatMessage]) -> str:
    system = msgs[0].content
    if system.startswith("You read a message a user typed"):
        message = msgs[-1].content.rsplit("Message: ", 1)[-1]
        if message.startswith("remove the Budget"):
            plan = {
                "needs_vault": True,
                "steps": [step("edit", folders=["Clients"], detail=message)],
                "question": "",
                "options": [],
            }
            return json.dumps(plan)
        return json.dumps({"needs_vault": False, "steps": [], "question": "", "options": []})
    if system.startswith("A user wants the same change made"):
        return json.dumps(
            {"kind": "remove", "section": "Budget", "instruction": "remove the Budget section"}
        )
    return "Usual chat answer."


async def ask(ai: AiEngine, text: str) -> str:
    out = ai.add_message(text)
    reply = ai.start_reply()
    async for _ in ai.answer(reply, out, EditorSnapshot()):
        pass
    return reply.text


async def test_edit_flow_through_the_chat(vault: Vault) -> None:
    index = Index(vault)
    index.sync()
    fake = FakeProvider(delay=0, script=backend)
    ai = AiEngine(vault, Config(vault=vault.root), index, provider_factory=lambda _c: fake)
    ai.allow()
    text = await ask(ai, "remove the Budget section from my client notes")
    assert "1 note would change" in text and "Nothing is changed yet" in text
    assert vault.read_text("Clients/Acme.md") == ACME  # the review comes first
    other = await ask(ai, "what is the weather?")  # not an answer: the review is dropped
    assert other == "Usual chat answer." and vault.read_text("Clients/Acme.md") == ACME
    await ask(ai, "remove the Budget section from my client notes")
    applied = await ask(ai, "Apply all")
    assert applied.startswith("Changed 1 note: Acme.") and "Undo" in applied
    assert "## Budget" not in vault.read_text("Clients/Acme.md")
    undone = await ask(ai, "Undo")
    assert undone.startswith("Put back 1 note") and vault.read_text("Clients/Acme.md") == ACME


async def test_review_cancel_and_writer_from_the_app(vault: Vault) -> None:
    index = Index(vault)
    index.sync()
    fake = FakeProvider(delay=0, script=backend)
    ai = AiEngine(vault, Config(vault=vault.root), index, provider_factory=lambda _c: fake)
    ai.allow()
    calls: list[str] = []

    class Writer(VaultWriter):
        def write(self, path: str, before: str, after: str, reason: str) -> bool:
            calls.append(reason)
            return super().write(path, before, after, reason)

    ai.note_writer = Writer(vault)
    await ask(ai, "remove the Budget section from my client notes")
    assert (await ask(ai, "Cancel")).startswith("Cancelled") and calls == []
    await ask(ai, "remove the Budget section from my client notes")
    await ask(ai, "1")
    assert calls == ["before an AI change across notes"]  # history reason passed on


async def test_note_changed_after_the_review_gets_a_new_diff(vault: Vault) -> None:
    index = Index(vault)
    index.sync()
    fake = FakeProvider(delay=0, script=backend)
    ai = AiEngine(vault, Config(vault=vault.root), index, provider_factory=lambda _c: fake)
    ai.allow()
    await ask(ai, "remove the Budget section from my client notes")
    typed = ACME.replace("Jane", "Jane and Joe")
    vault.write_text("Clients/Acme.md", typed)  # the user typed meanwhile
    again = await ask(ai, "Apply all")
    assert "changed after the diff was made; here is the change again" in again
    assert vault.read_text("Clients/Acme.md") == typed  # never written over
    await ask(ai, "Apply all")
    assert vault.read_text("Clients/Acme.md") == typed.replace("## Budget\n\n10k\n\n", "")
