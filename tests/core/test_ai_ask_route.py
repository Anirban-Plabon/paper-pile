"""The Ask box's edit-or-answer decision (PLAN §4.27): first words, else the model."""

from pathlib import Path

import pytest

from paper_pile.core.ai.ask_route import ROUTE_SCHEMA, route, route_by_words
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault


@pytest.mark.parametrize(
    "message",
    [
        "Rewrite this more formally",
        "rephrase",
        "please make it shorter",
        "Can you fix the grammar?",
        "could you please translate this to French",
        "Turn it into a bullet list",
        "write it as a haiku",
        "SHORTEN!",
        "change 'cat' to 'dog'",
    ],
)
def test_edit_words(message: str) -> None:
    assert route_by_words(message) == "edit"


@pytest.mark.parametrize(
    "message",
    [
        "What does this mean?",
        "Explain this",
        "why is the sky blue",
        "Summarize it",
        "can you tell me who wrote this?",
        "is the change correct?",
        "",
        "please",
    ],
)
def test_question_words(message: str) -> None:
    assert route_by_words(message) == "answer"


@pytest.mark.parametrize(
    "message",
    ["put it in quote", "bold the names", "this as a table", "write a poem about cats", "add one"],
)
def test_unclear_words_go_to_the_model(message: str) -> None:
    assert route_by_words(message) is None


@pytest.fixture
def setup(tmp_path: Path) -> tuple[AiEngine, FakeProvider]:
    vault = Vault(tmp_path / "v")
    vault.root.mkdir()
    fake = FakeProvider(delay=0)
    ai = AiEngine(vault, Config(vault=vault.root), provider_factory=lambda _c: fake)
    ai.allow()
    return ai, fake


async def test_model_decides_an_edit(setup: tuple[AiEngine, FakeProvider]) -> None:
    ai, fake = setup
    fake.script = ['{"action": "edit"}']
    assert await route(ai, "put it in quote", "Some paragraph.") == "edit"
    assert len(fake.calls) == 1
    sent = fake.calls[0][-1].content
    assert "Some paragraph." in sent and "put it in quote" in sent
    assert fake.options is not None and fake.options.schema == ROUTE_SCHEMA


async def test_model_decides_an_answer(setup: tuple[AiEngine, FakeProvider]) -> None:
    ai, fake = setup
    fake.script = ['{"action": "answer"}']
    assert await route(ai, "write a poem about cats", "Cats.") == "answer"


async def test_clear_words_need_no_model(setup: tuple[AiEngine, FakeProvider]) -> None:
    ai, fake = setup
    assert await route(ai, "rewrite it", "x") == "edit"
    assert await route(ai, "what is this?", "x") == "answer"
    assert fake.calls == []


@pytest.mark.parametrize("reply", ["not json", '{"action": "dance"}', "{}"])
async def test_nonsense_from_the_model_answers(
    setup: tuple[AiEngine, FakeProvider], reply: str
) -> None:
    ai, fake = setup
    fake.script = [reply]
    assert await route(ai, "bold the names", "Ana and Bo") == "answer"


async def test_failing_model_answers(setup: tuple[AiEngine, FakeProvider]) -> None:
    ai, fake = setup
    fake.fail_calls = 1
    assert await route(ai, "bold the names", "Ana and Bo") == "answer"


async def test_long_selection_is_cut(setup: tuple[AiEngine, FakeProvider]) -> None:
    ai, fake = setup
    fake.script = ['{"action": "edit"}']
    await route(ai, "bold the names", "word " * 2000)
    assert len(fake.calls[0][-1].content) < 2000
