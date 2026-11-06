"""The vault agent inside the chat (PLAN_vault_agent P30.49): ``AiEngine.answer`` asks the
agent first and falls back to the usual answer — end to end with a scripted backend that
answers each prompt by its rules."""

import json
from pathlib import Path

import pytest

from paper_pile.core.ai.context import EditorSnapshot
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.provider import ChatMessage
from paper_pile.core.ai.vault.plan import Choice
from paper_pile.core.ai.vault.session import picked_option, question_text, wants_agent
from paper_pile.core.config import Config, scope_for
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault


def step(action: str = "locate", **kw: object) -> dict[str, object]:
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


class Backend:
    """Answers by which prompt it is: understanding (``plan`` per message), judge (yes when
    the card mentions microcredit), more terms (none), else the usual chat echo."""

    def __init__(self) -> None:
        self.plans: dict[str, dict[str, object]] = {}
        self.kinds: list[str] = []

    def __call__(self, msgs: list[ChatMessage]) -> str:
        system = msgs[0].content
        user = msgs[-1].content
        if system.startswith("You read a message a user typed"):
            self.kinds.append("understand")
            message = user.rsplit("Message: ", 1)[-1]
            return json.dumps(
                self.plans.get(
                    message, {"needs_vault": False, "steps": [], "question": "", "options": []}
                )
            )
        if system.startswith("You decide which of a user's notes"):
            self.kinds.append("judge")
            cards = user.split("\n\n")[2:]
            return json.dumps(
                {
                    "verdicts": [
                        {
                            "n": n,
                            "relevance": "yes" if "microcredit" in c.lower() else "no",
                            "reason": "on topic",
                        }
                        for n, c in enumerate(cards, 1)
                    ]
                }
            )
        if system.startswith("A user is looking for all their notes"):
            self.kinds.append("expand")
            return json.dumps({"terms": []})
        if system.startswith("You write an index card"):
            self.kinds.append("card")
            return json.dumps({"summary": "A note.", "terms": []})
        if system.startswith("You answer a question") or system.startswith("You summarise"):
            self.kinds.append("answer")
            return "From the notes [1]."
        self.kinds.append("chat")
        return "Usual chat answer."


@pytest.fixture
def setup(tmp_path: Path) -> tuple[AiEngine, Backend]:
    vault = Vault(tmp_path / "v")
    vault.root.mkdir()
    vault.create_note("Research/Yunus.md", "# Yunus\nmicrocredit for the poor\n")
    vault.create_note("Research/Bank.md", "# Bank\nmicrocredit groups\n")
    vault.create_note("Pricing.md", "# Pricing\nprices\n")
    vault.create_note("Clients/Pricing.md", "# Client pricing\nmicrocredit rates\n")
    vault.create_note("Private/Secret.md", "---\nai: false\n---\nmicrocredit secret\n")
    index = Index(vault)
    index.sync()
    backend = Backend()
    fake = FakeProvider(delay=0, script=backend)
    cfg = Config(vault=vault.root)
    ai = AiEngine(vault, cfg, index, provider_factory=lambda _c: fake)
    ai.allow()
    return ai, backend


def mode(ai: AiEngine, value: str) -> None:
    assert ai.config is not None
    ai.config.set("ai.vault_agent", value, scope_for("ai.vault_agent", "vault"))


async def ask(ai: AiEngine, text: str, **kw: object) -> tuple[str, list[str], str]:
    out = ai.add_message(text, **kw)  # type: ignore[arg-type]
    reply = ai.start_reply()
    statuses: list[str] = []
    pieces = [p async for p in ai.answer(reply, out, EditorSnapshot(), on_status=statuses.append)]
    assert "".join(pieces) == reply.text
    return reply.text, reply.sources, reply.summary


def test_wants_agent_and_options() -> None:
    assert wants_agent("auto", False, False) and not wants_agent("auto", False, True)
    assert wants_agent("auto", True, True) and wants_agent("at", True, False)
    assert not wants_agent("at", False, False) and not wants_agent("off", True, False)
    choice = Choice(
        "Which?", ("Clients/Pricing", "Pricing"), ("Clients/Pricing.md", "Pricing.md"), "note"
    )
    assert picked_option(choice, "2") == "Pricing.md"
    assert picked_option(choice, " clients/pricing ") == "Clients/Pricing.md"
    assert picked_option(choice, "something else") is None and picked_option(choice, "7") is None
    assert question_text(choice).splitlines()[2:4] == ["1. Clients/Pricing", "2. Pricing"]


async def test_vault_request_answered_by_the_agent(setup: tuple[AiEngine, Backend]) -> None:
    ai, backend = setup
    backend.plans["where are my microcredit notes?"] = {
        "needs_vault": True,
        "steps": [
            step(
                topic="microcredit", terms=["microcredit"], detail="where are my microcredit notes"
            )
        ],
        "question": "",
        "options": [],
    }
    text, sources, summary = await ask(ai, "where are my microcredit notes?")
    assert text.startswith("Found 3 notes.") and "Secret" not in text
    assert set(sources) == {"Research/Yunus.md", "Research/Bank.md", "Clients/Pricing.md"}
    assert summary == "Vault: 3 notes" and "chat" not in backend.kinds
    # the follow-up sees the last result
    assert ai.vault_session().last is not None and len(ai.vault_session().last or []) == 3


async def test_not_a_vault_request_gets_the_usual_answer(setup: tuple[AiEngine, Backend]) -> None:
    ai, backend = setup
    text, _, _ = await ask(ai, "what is the capital of France?")
    assert text == "Usual chat answer." and backend.kinds == ["understand", "chat"]


async def test_attached_notes_skip_the_agent(setup: tuple[AiEngine, Backend]) -> None:
    ai, backend = setup
    text, _, _ = await ask(ai, "summarise this", notes=["Pricing.md"])
    assert text == "Usual chat answer." and "understand" not in backend.kinds
    await ask(ai, "what does @Pricing say?")  # an @note mention is an attachment too
    assert "understand" not in backend.kinds
    mode(ai, "off")
    await ask(ai, "@vault where is microcredit?")
    assert "understand" not in backend.kinds  # off: the old @vault search, no agent


async def test_at_mode_only_with_scopes(setup: tuple[AiEngine, Backend]) -> None:
    ai, backend = setup
    mode(ai, "at")
    await ask(ai, "where are my microcredit notes?")
    assert backend.kinds == ["chat"]


async def test_ambiguous_note_asks_and_the_next_message_answers(
    setup: tuple[AiEngine, Backend],
) -> None:
    ai, backend = setup
    backend.plans["summarise Pricing"] = {
        "needs_vault": True,
        "steps": [
            step("summarise", topic="Pricing", notes=["Pricing"], detail="summarise Pricing")
        ],
        "question": "",
        "options": [],
    }
    text, _, summary = await ask(ai, "summarise Pricing")
    assert text.startswith("Which note do you mean by “Pricing”?")
    assert "1. Clients/Pricing" in text and summary == "Vault: a question first"
    answered, sources, _ = await ask(ai, "1")
    assert answered.startswith("From the notes [1].") and sources == ["Clients/Pricing.md"]
    assert backend.kinds.count("understand") == 1  # the answer did not need a new understanding


async def test_folder_scope_reaches_the_steps(setup: tuple[AiEngine, Backend]) -> None:
    ai, backend = setup
    backend.plans["where is microcredit?"] = {
        "needs_vault": True,
        "steps": [
            step(topic="microcredit", terms=["microcredit"])
        ],  # the model left the folder out
        "question": "",
        "options": [],
    }
    text, sources, _ = await ask(ai, "@Research/ where is microcredit?")
    assert set(sources) == {"Research/Yunus.md", "Research/Bank.md"}  # Clients/ left out
    assert "Clients" not in text


async def test_new_chat_forgets_the_last_result(setup: tuple[AiEngine, Backend]) -> None:
    ai, backend = setup
    backend.plans["summarise Pricing"] = {
        "needs_vault": True,
        "steps": [step("summarise", notes=["Pricing"])],
        "question": "",
        "options": [],
    }
    await ask(ai, "summarise Pricing")
    assert ai.vault_session().pending is not None
    ai.new_chat()
    assert ai.vault_session().pending is None and ai.vault_session().last is None


async def test_payload_on_the_saved_reply(setup: tuple[AiEngine, Backend]) -> None:
    ai, backend = setup
    backend.plans["where are my microcredit notes?"] = {
        "needs_vault": True,
        "steps": [step(topic="microcredit", terms=["microcredit"])],
        "question": "",
        "options": [],
    }
    await ask(ai, "where are my microcredit notes?")
    vault = ai.turns[-1].vault
    assert vault["kind"] == "answer" and vault["steps"] == []
    labels = [c["label"] for c in vault["chips"]]
    assert "Summarise all" in labels and "Open all" in labels
    backend.plans["summarise Pricing"] = {
        "needs_vault": True,
        "steps": [step("summarise", notes=["Pricing"])],
        "question": "",
        "options": [],
    }
    await ask(ai, "summarise Pricing")
    question = ai.turns[-1].vault
    assert question["kind"] == "question"
    assert [c["send"] for c in question["chips"]] == ["Clients/Pricing", "Pricing"]
    await ask(ai, "Clients/Pricing")  # what the chip sends answers the question
    answered = ai.turns[-1].vault
    assert answered["kind"] == "answer" and answered["cites"][0]["path"] == "Clients/Pricing.md"
