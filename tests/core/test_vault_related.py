"""Related notes (PLAN_vault_agent P30.39 / P30.42): an @vault request about an attached note
leaves that note out of its results, and "Link them here" links the found notes into it — only
the ones it does not link yet — as a review."""

import json
from pathlib import Path

from paper_pile.core.ai.context import EditorSnapshot
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.provider import ChatMessage
from paper_pile.core.ai.vault.session import related_section
from paper_pile.core.config import Config
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault


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
    system, user = msgs[0].content, msgs[-1].content
    if system.startswith("You read a message a user typed"):
        plan = [step("locate", topic="microcredit", terms=["microcredit"])]
        return json.dumps({"needs_vault": True, "steps": plan, "question": "", "options": []})
    if system.startswith("You decide which of a user's notes"):
        cards = user.split("\n\n")[2:]
        verdicts = [
            {"n": n, "relevance": "yes", "reason": "same subject"} for n in range(1, len(cards) + 1)
        ]
        return json.dumps({"verdicts": verdicts})
    if system.startswith("A user is looking for all their notes"):
        return json.dumps({"terms": []})
    return "Usual chat answer."


async def ask(ai: AiEngine, text: str, notes: list[str] | None = None) -> str:
    out = ai.add_message(text, notes=notes or [])
    reply = ai.start_reply()
    async for _ in ai.answer(reply, out, EditorSnapshot()):
        pass
    return reply.text


def test_related_section() -> None:
    assert related_section("# A\ntext\n", ["- [[B]]"]) == "# A\ntext\n\n## Related\n\n- [[B]]\n"
    with_one = "# A\n\n## Related\n\n- [[B]]\n\n## Later\n\nx\n"
    assert related_section(with_one, ["- [[C]]"]) == (
        "# A\n\n## Related\n\n- [[B]]\n- [[C]]\n\n## Later\n\nx\n"
    )


async def test_related_notes_and_link_them_here(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "v")
    vault.root.mkdir()
    vault.create_note(
        "Research/Yunus.md", "# Yunus\n\nMicrocredit for the poor. See [[Grameen]].\n"
    )
    vault.create_note("Research/Bank.md", "# Bank\n\nMicrocredit groups.\n")
    vault.create_note("Research/Grameen.md", "# Grameen\n\nA microcredit bank.\n")
    index = Index(vault)
    index.sync()
    fake = FakeProvider(delay=0, script=backend)
    ai = AiEngine(vault, Config(vault=vault.root), index, provider_factory=lambda _c: fake)
    ai.allow()
    found = await ask(
        ai, "@vault Which other notes are about the same subject as “Yunus”", ["Research/Yunus.md"]
    )
    assert "Bank" in found and "Grameen" in found
    assert "pp-note:Research/Yunus.md" not in found  # not its own related note
    assert ai.turns[-1].vault["chips"][0]["label"] == "Link them here"
    review = await ask(ai, "Link them here")
    assert (
        "+ - [[Bank]]" in review and "Grameen]]" not in review.split("```diff", 1)[1]
    )  # linked already
    assert vault.read_text("Research/Yunus.md").count("Related") == 0  # nothing written yet
    await ask(ai, "Apply all")
    text = vault.read_text("Research/Yunus.md")
    assert text.endswith("## Related\n\n- [[Bank]]\n") and "See [[Grameen]]." in text
