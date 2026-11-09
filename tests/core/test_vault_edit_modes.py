"""P31.2 / P31.4 (PLAN §4.32): the chat's vault-agent changes follow ``ai.edits`` — written at
once (*Apply at once*) or handed to the app's writer to show in the notes (*Review in the
note*) — and never become a question in the chat. A writer that cannot show diffs keeps the
old chat review (tools); the memory file follows the same mode."""

import json
from pathlib import Path

import pytest

from paper_pile.core.ai.context import EditorSnapshot
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.provider import ChatMessage
from paper_pile.core.ai.vault.edits import EditBatch, VaultWriter
from paper_pile.core.ai.vault.memory import read_memory_file
from paper_pile.core.config import Config, scope_for
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault

ACME = "# Acme\n\nIntro.\n\n## Budget\n\n10k\n\n## Contacts\n\nJane\n"


def step(action: str, **kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "action": action,
        "meta": "none",
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
        "uses_answer": False,
        "detail": "",
        "depends_on": -1,
    }
    base.update(kw)
    return base


def script(msgs: list[ChatMessage]) -> str:
    system, user = msgs[0].content, msgs[-1].content
    if system.startswith("You read a message a user typed"):
        message = user.rsplit("Message: ", 1)[-1]
        if message == "remove the Budget section here":  # the attached note (no target named)
            plan = {"needs_vault": True, "steps": [step("edit")], "question": "", "options": []}
            return json.dumps(plan)
        if message.startswith("rewrite them"):  # the previous answer's notes
            plan = {
                "needs_vault": True,
                "steps": [step("edit", from_result="all")],
                "question": "",
                "options": [],
            }
            return json.dumps(plan)
        if message.startswith("find budgets"):  # a search through the vault
            plan = {
                "needs_vault": True,
                "steps": [step("locate", topic="budget", terms=["budget"])],
                "question": "",
                "options": [],
            }
            return json.dumps(plan)
        if message.startswith("remove the Budget"):
            plan = {
                "needs_vault": True,
                "steps": [step("edit", folders=["Clients"])],
                "question": "",
                "options": [],
            }
            return json.dumps(plan)
        if message.startswith("remember"):
            plan = {
                "needs_vault": True,
                "steps": [step("remember", detail=message.removeprefix("remember that "))],
                "question": "",
                "options": [],
            }
            return json.dumps(plan)
        return json.dumps({"needs_vault": False, "steps": [], "question": "", "options": []})
    if system.startswith("A user selected text"):  # the Ask box's understanding
        return json.dumps(
            {
                "want": "change",
                "complete": True,
                "question": "",
                "options": [],
                "reach": "note",
                "size": "medium",
                "adds": False,
                "new_form": False,
            }
        )
    if system.startswith("A user wants a change made"):
        return json.dumps({"kind": "remove", "section": "Budget", "instruction": "remove it"})
    return "Usual chat answer."


class Reviewer(VaultWriter):
    """The app's writer, as far as the session sees it: it can show changes for review."""

    def __init__(self, vault: Vault) -> None:
        super().__init__(vault)
        self.shown: list[EditBatch] = []
        self.memory: list[tuple[str, str]] = []

    async def review(self, batch: EditBatch) -> bool:
        self.shown.append(batch)
        return True

    async def review_memory(self, before: str, after: str) -> bool:
        self.memory.append((before, after))
        return True


@pytest.fixture
def ai(tmp_path: Path) -> AiEngine:
    vault = Vault(tmp_path / "v")
    vault.root.mkdir()
    vault.create_note("Clients/Acme.md", ACME)
    index = Index(vault)
    index.sync()
    fake = FakeProvider(delay=0, script=script)
    engine = AiEngine(vault, Config(vault=vault.root), index, provider_factory=lambda _c: fake)
    engine.allow()
    return engine


def mode(ai: AiEngine, value: str) -> None:
    assert ai.config is not None
    ai.config.set("ai.edits", value, scope_for("ai.edits", "vault"))


async def ask(ai: AiEngine, text: str) -> tuple[str, dict[str, object]]:
    out = ai.add_message(text)
    reply = ai.start_reply()
    async for _ in ai.answer(reply, out, EditorSnapshot()):
        pass
    return reply.text, reply.vault or {}


async def test_apply_at_once_writes_without_asking(ai: AiEngine) -> None:
    mode(ai, "auto")
    text, payload = await ask(ai, "remove the Budget section from my client notes")
    assert text.startswith("Changed 1 note: [Acme](<pp-note:Clients/Acme.md>).")
    assert "Apply all" not in text and "Undo" not in text and "Nothing is changed" not in text
    assert payload.get("kind") == "applied" and not payload.get("chips")
    assert "## Budget" not in ai.vault.read_text("Clients/Acme.md")
    undone, _ = await ask(ai, "Undo")  # typed, it still puts the note back
    assert undone.startswith("Put back 1 note") and ai.vault.read_text("Clients/Acme.md") == ACME


async def test_review_in_the_note_hands_the_changes_to_the_writer(ai: AiEngine) -> None:
    mode(ai, "ask")
    writer = Reviewer(ai.vault)
    ai.note_writer = writer
    text, payload = await ask(ai, "remove the Budget section from my client notes")
    assert len(writer.shown) == 1 and [e.path for e in writer.shown[0].ready] == ["Clients/Acme.md"]
    assert "shown in the note" in text and "pp-note:Clients/Acme.md" in text
    assert "Apply all" not in text and payload.get("kind") == "proposed"
    assert ai.vault.read_text("Clients/Acme.md") == ACME  # nothing written by the chat
    other, _ = await ask(ai, "Apply all")  # no gate in the chat to answer
    assert "no longer open" in other and ai.vault.read_text("Clients/Acme.md") == ACME


async def test_a_writer_that_cannot_show_diffs_keeps_the_chat_review(ai: AiEngine) -> None:
    mode(ai, "ask")  # tools and tests: VaultWriter has no review
    text, _ = await ask(ai, "remove the Budget section from my client notes")
    assert "1 note would change" in text and "Nothing is changed yet" in text


async def test_the_memory_file_follows_the_mode(ai: AiEngine) -> None:
    mode(ai, "auto")
    text, _ = await ask(ai, "remember that client notes are in Clients")
    assert text.startswith("Saved to the notes for the AI")
    assert "client notes are in Clients" in read_memory_file(ai.vault.root)
    mode(ai, "ask")
    writer = Reviewer(ai.vault)
    ai.note_writer = writer
    text, _ = await ask(ai, "remember that budgets are in a Budget section")
    assert writer.memory and "open to save" in text  # the editor opened with the change


async def test_on_a_remote_ai_only_notes_beyond_the_given_ones_need_the_permission(
    ai: AiEngine,
) -> None:
    """The notes the user gave (attached, open on screen) are the chat's direct notes: edited
    without a permission question. Going beyond them (a folder, a search) asks always / this
    session / no; after "Allow this session" nothing asks again (PLAN §4.32)."""
    from paper_pile.core.ai.edit_run import EditResult, EditRun
    from paper_pile.core.ai.proposals import propose

    async def cut(self: EditRun) -> EditResult:  # the edit pipeline: the Budget section goes
        a, b = self.note.index("## Budget"), self.note.index("## Contacts")
        return EditResult(propose(self.path, self.note, a, b, ""), [])

    original = EditRun.run
    EditRun.run = cut  # type: ignore[method-assign]
    ai.provider.local = False  # type: ignore[misc]
    mode(ai, "auto")
    out = ai.add_message("remove the Budget section here", notes=["Clients/Acme.md"])
    reply = ai.start_reply()
    async for _ in ai.answer(reply, out, EditorSnapshot()):
        pass
    EditRun.run = original  # type: ignore[method-assign]
    assert reply.text.startswith("Changed 1 note")  # the attached note: no question
    ai.vault.write_text("Clients/Acme.md", ACME)
    text, _ = await ask(ai, "remove the Budget section from my client notes")  # a folder
    assert text.startswith("The agent may not read or edit your vault")
    assert ai.vault.read_text("Clients/Acme.md") == ACME  # nothing read or changed
    done, _ = await ask(ai, "Allow this session")
    assert done.startswith("Changed 1 note")
    text, _ = await ask(ai, "remember that client notes are in Clients")
    assert text.startswith("Saved to the notes for the AI")  # no second question
