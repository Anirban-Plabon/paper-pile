"""The Ask box under a selection (PLAN §4.27): rewrite-or-ask and the box's prompt."""

from pathlib import Path

import pytest

from paper_pile.core.ai.access import AccessDeniedError
from paper_pile.core.ai.edits import EditTooLongError
from paper_pile.core.ai.engine import DIVIDER, AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.selection_ask import AskTurn, box_commands, wants_edit
from paper_pile.core.commands import CommandContext
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
def test_edit_requests(message: str) -> None:
    assert wants_edit(message)


@pytest.mark.parametrize(
    "message",
    [
        "What does this mean?",
        "Explain this",
        "why is the sky blue",
        "Summarize it",
        "can you tell me who wrote this?",
        "write a poem about cats",
        "is the change correct?",
        "",
        "please",
    ],
)
def test_questions(message: str) -> None:
    assert not wants_edit(message)


@pytest.fixture
def setup(tmp_path: Path) -> tuple[AiEngine, FakeProvider, Vault]:
    vault = Vault(tmp_path / "v")
    vault.root.mkdir()
    vault.create_note("a.md", "# A\nalpha body\n")
    fake = FakeProvider(delay=0)
    ai = AiEngine(vault, Config(vault=vault.root), provider_factory=lambda _c: fake)
    ai.allow()
    return ai, fake, vault


async def test_selection_goes_with_the_first_question(
    setup: tuple[AiEngine, FakeProvider, Vault],
) -> None:
    ai, _fake, _vault = setup
    turns = [
        AskTurn("user", "What is it?"),
        AskTurn("assistant", "A letter."),
        AskTurn("user", "Which one?"),
    ]
    msgs = await ai.selection_messages(
        path="a.md", text="# A\nalpha body\n", selected="alpha", turns=turns
    )
    assert [m.role for m in msgs] == ["system", "user", "assistant", "user"]
    head = "selected this text in the note:\n\nalpha"
    assert msgs[1].content.endswith(head + DIVIDER + "What is it?")
    assert "alpha body" in msgs[1].content  # the open note goes in front
    assert msgs[3].content == "Which one?" and "alpha" not in msgs[3].content


async def test_old_exchanges_go_first_and_too_long_is_refused(
    setup: tuple[AiEngine, FakeProvider, Vault],
) -> None:
    ai, fake, _vault = setup
    fake.max_context = 1024  # room for the prompt: 512 tokens
    big = "word " * 400  # ~500 tokens
    turns = [
        AskTurn("user", "first"),
        AskTurn("assistant", big),
        AskTurn("user", "second"),
        AskTurn("assistant", "short"),
        AskTurn("user", "third"),
    ]
    msgs = await ai.selection_messages(path="a.md", text="x", selected="sel", turns=turns)
    assert [m.content for m in msgs[2:]] == ["short", "third"]
    assert "first" in msgs[1].content
    with pytest.raises(EditTooLongError, match="Select less"):
        await ai.selection_messages(
            path="a.md", text="x", selected="word " * 600, turns=[AskTurn("user", "q")]
        )
    assert not fake.calls


async def test_a_note_the_ai_may_not_read(setup: tuple[AiEngine, FakeProvider, Vault]) -> None:
    ai, _fake, _vault = setup
    private = "---\nai: false\n---\nsecret"
    with pytest.raises(AccessDeniedError):
        await ai.selection_messages(
            path="a.md", text=private, selected="secret", turns=[AskTurn("user", "q")]
        )


def test_the_slash_list() -> None:
    import paper_pile.core.commands_builtin  # noqa: F401  (registers the commands)

    ctx = CommandContext("a.md", "teh cat", 0, selection=(0, 7))
    ids = [c.id for c in box_commands("", ctx)]
    assert ids == [
        "ai-rewrite",
        "ai-tone",
        "ai-summarize",
        "ai-explain",
        "ai-outline",
        "ai-translate",
        "delete",
    ]
    assert [c.id for c in box_commands("gram", ctx)] == ["ai-rewrite"]  # an alias
    assert [c.id for c in box_commands("rem", ctx)] == ["delete"]
    assert [c.title for c in box_commands("expl", ctx)] == ["Explain"]
    assert box_commands("heading", ctx) == []  # only AI commands and Delete


async def test_the_box_conversation_becomes_a_saved_chat(
    setup: tuple[AiEngine, FakeProvider, Vault],
) -> None:
    from paper_pile.core.ai.chats import load_chat

    ai, _fake, _vault = setup
    ai.chat_from_box(
        "alpha", "a.md", [AskTurn("user", "What is it?"), AskTurn("assistant", "A letter.")]
    )
    assert [t.role for t in ai.turns] == ["user", "assistant"]
    assert ai.turns[0].quotes[0].text == "alpha" and ai.turns[0].quotes[0].note == "a"
    saved = load_chat(ai.chats_dir(), ai.chat_id)
    assert saved is not None and saved.turns[1].text == "A letter."
