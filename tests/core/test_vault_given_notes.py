"""The chat's direct notes (user 2026-11-09, PLAN §4.32): notes attached to a message and the
notes open on screen (both sides of a split view) are what a message is about. A change to them
needs no "which note?" — the harness decides (every attached note, else the active open note) —
and goes to the edit pipeline with the user's own words, like the Ask box."""

import json
from pathlib import Path
from typing import Any

import pytest

from paper_pile.core.ai.context import EditorSnapshot
from paper_pile.core.ai.edit_run import EditResult, EditRun
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.proposals import propose
from paper_pile.core.ai.provider import ChatMessage
from paper_pile.core.ai.vault.session import no_target_question
from paper_pile.core.ai.vault.understand import RequestContext, messages, parse
from paper_pile.core.config import Config, scope_for
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault

DAY1, DAY2 = "# 08-Nov\n\nMorning.\n", "# 09-Nov\n\nEvening.\n"


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


class Script:
    """Understanding asks "which note?" (as Gemini did); records every prompt kind."""

    def __init__(self) -> None:
        self.kinds: list[str] = []
        self.understood: list[str] = []

    def __call__(self, msgs: list[ChatMessage]) -> str:
        system, user = msgs[0].content, msgs[-1].content
        if system.startswith("You read a message a user typed"):
            self.kinds.append("understand")
            self.understood.append(user)
            plan = {
                "needs_vault": True,
                "steps": [step("edit", detail="add a paragraph on CMOS")],
                "question": "Which note should the paragraph be added to?",
                "options": ["08-Nov", "09-Nov", "A new note"],
            }
            return json.dumps(plan)
        if system.startswith("A user selected text"):  # the Ask box's understanding
            self.kinds.append("intent")
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
            self.kinds.append("target")
            return json.dumps({"kind": "add", "section": "", "instruction": "x"})
        self.kinds.append("chat")
        return "Usual chat answer."


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[AiEngine, Script, list[str]]:
    vault = Vault(tmp_path / "v")
    vault.root.mkdir()
    vault.create_note("Days/08-Nov.md", DAY1)
    vault.create_note("Days/09-Nov.md", DAY2)
    index = Index(vault)
    index.sync()
    script = Script()
    fake = FakeProvider(delay=0, script=script)
    ai = AiEngine(vault, Config(vault=vault.root), index, provider_factory=lambda _c: fake)
    ai.allow()
    assert ai.config is not None
    ai.config.set("ai.edits", "auto", scope_for("ai.edits", "vault"))
    told: list[str] = []

    async def run(self: EditRun) -> EditResult:  # the edit pipeline: add a line at the end
        told.append(self.instruction)
        end = len(self.note)
        return EditResult(propose(self.path, self.note, end, end, "\nCMOS.\n"), [])

    monkeypatch.setattr(EditRun, "run", run)
    return ai, script, told


async def ask(ai: AiEngine, text: str, snap: EditorSnapshot, **kw: Any) -> str:
    out = ai.add_message(text, **kw)
    reply = ai.start_reply()
    async for _ in ai.answer(reply, out, snap):
        pass
    return reply.text


async def test_two_attached_notes_are_edited_without_asking_which(
    setup: tuple[AiEngine, Script, list[str]],
) -> None:
    ai, script, told = setup
    message = "write a short paragraph on cmos in"
    text = await ask(ai, message, EditorSnapshot(), notes=["Days/08-Nov.md", "Days/09-Nov.md"])
    assert "Which note" not in text and text.startswith("Changed 2 notes")
    assert ai.vault.read_text("Days/08-Nov.md").endswith("CMOS.\n")
    assert ai.vault.read_text("Days/09-Nov.md").endswith("CMOS.\n")
    assert "target" not in script.kinds  # no rewording call: the user's words go to the edit
    assert "understand" not in script.kinds  # attached notes: never the vault's understanding
    assert told == [message, message]


async def test_the_split_views_other_note_is_on_screen_too(
    setup: tuple[AiEngine, Script, list[str]],
) -> None:
    ai, script, told = setup
    snap = EditorSnapshot(path="Days/08-Nov.md", text=DAY1, other="Days/09-Nov.md")
    context = ai.chat_context(snap, "compare them")
    sent = " ".join(p.text for p in context.parts)
    assert "Evening." in sent and "Morning." in sent  # both sides of the split are sent
    text = await ask(ai, "add a line about cmos to this note", snap)
    assert "Also open (the other side of a split view): 09-Nov" in script.understood[-1]
    assert text.startswith("Changed 1 note")  # "this note": the active side
    assert ai.vault.read_text("Days/08-Nov.md").endswith("CMOS.\n")
    assert ai.vault.read_text("Days/09-Nov.md") == DAY2


def test_no_target_question_only_for_the_given_notes() -> None:
    from datetime import date

    def req(**kw: object) -> Any:
        raw = {
            "needs_vault": True,
            "steps": [step("edit", **kw)],
            "question": "Which?",
            "options": ["a", "b"],
        }
        found = parse(raw, date(2026, 11, 9))
        assert found is not None
        return found

    assert no_target_question(req(notes=["A"]), ["A", "B"]).question == ""
    assert no_target_question(req(), ["A"]).question == ""
    assert no_target_question(req(notes=["C"]), ["A"]).question == "Which?"  # another note
    assert no_target_question(req(terms=["x"]), ["A"]).question == "Which?"  # a search
    assert no_target_question(req(folders=["F"]), ["A"]).question == "Which?"
    assert no_target_question(req(notes=["A"]), []).question == "Which?"  # nothing given
    ctx = RequestContext(date(2026, 11, 9), open_note="A", other_note="B")
    shown = messages("x", ctx)[1].content
    assert "Open note (active): A" in shown and "other side of a split view): B" in shown
