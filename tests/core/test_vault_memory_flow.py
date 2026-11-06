"""The vault memory file (PLAN_vault_agent §5.6, P30.28): edited by the user, added to by
"remember …" in the chat after a review; never deleted."""

import json
from pathlib import Path

from paper_pile.core.ai.context import EditorSnapshot
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.provider import ChatMessage
from paper_pile.core.ai.vault.memory import (
    load_memory,
    memory_path,
    read_memory_file,
    save_memory,
    with_fact,
)
from paper_pile.core.config import Config
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault


def test_memory_helpers(tmp_path: Path) -> None:
    assert read_memory_file(tmp_path) == ""
    save_memory(tmp_path, "- Daily notes in Journal/\n\n")
    assert read_memory_file(tmp_path) == "- Daily notes in Journal/\n"
    save_memory(tmp_path, "   ")
    assert memory_path(tmp_path).exists() and read_memory_file(tmp_path) == ""  # emptied, kept
    assert with_fact("", "Clients are in Clients/") == "- Clients are in Clients/\n"
    text = with_fact("- a\n", "  b  ")
    assert text == "- a\n- b\n" and with_fact(text, "b") == text  # no repeat


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
    if msgs[0].content.startswith("You read a message a user typed"):
        message = msgs[-1].content.rsplit("Message: ", 1)[-1]
        if message.startswith("remember"):
            fact = "Daily notes are in Journal/ as YYYY-MM-DD"
            return json.dumps(
                {
                    "needs_vault": True,
                    "steps": [step("remember", detail=fact)],
                    "question": "",
                    "options": [],
                }
            )
        return json.dumps({"needs_vault": False, "steps": [], "question": "", "options": []})
    return "Usual chat answer."


async def ask(ai: AiEngine, text: str) -> str:
    out = ai.add_message(text)
    reply = ai.start_reply()
    async for _ in ai.answer(reply, out, EditorSnapshot()):
        pass
    return reply.text


async def test_remember_through_the_chat(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "v")
    vault.root.mkdir()
    vault.create_note("a.md", "x\n")
    index = Index(vault)
    index.sync()
    fake = FakeProvider(delay=0, script=backend)
    ai = AiEngine(vault, Config(vault=vault.root), index, provider_factory=lambda _c: fake)
    ai.allow()
    shown = await ask(ai, "remember that my daily notes are in Journal")
    assert "+ - Daily notes are in Journal/ as YYYY-MM-DD" in shown
    assert read_memory_file(vault.root) == ""  # shown first, nothing written
    assert [c["label"] for c in ai.turns[-1].vault["chips"]] == ["Save", "Cancel"]
    assert (await ask(ai, "Save")).startswith("Saved to the notes for the AI")
    assert load_memory(vault.root) == "- Daily notes are in Journal/ as YYYY-MM-DD"
    again = await ask(ai, "remember that my daily notes are in Journal")
    assert again == "That is already in the notes for the AI."
