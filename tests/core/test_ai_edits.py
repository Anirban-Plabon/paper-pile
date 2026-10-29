"""AI changes to notes (PLAN §4.26, P23.3–P23.4): the mode table, finished answers only, and the
replacement text cleaned of what real models wrap around it."""

import asyncio
from pathlib import Path

import pytest

from paper_pile.core.ai.context import EditorSnapshot
from paper_pile.core.ai.edits import (
    EditTooLongError,
    clean_reply,
    edit_action,
    edit_mode,
    replacement_action,
)
from paper_pile.core.ai.engine import BUSY, CUT_OFF, AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.provider import ProviderError
from paper_pile.core.commands import StreamInsert
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault


@pytest.mark.parametrize(
    ("mode", "kind", "action"),
    [
        ("ask", "insert", "stream"),
        ("auto", "insert", "stream"),
        ("readonly", "insert", "refuse"),
        ("ask", "replace", "propose"),
        ("auto", "replace", "apply"),
        ("readonly", "replace", "show"),
    ],
)
def test_edit_action_table(mode: str, kind: str, action: str) -> None:
    assert edit_action(edit_mode(mode), kind) == action  # type: ignore[arg-type]


def test_unknown_mode_is_ask() -> None:
    assert edit_mode("always") == "ask" and edit_mode(None) == "ask"


def test_only_a_finished_answer_replaces_text() -> None:
    old = "one two three four five six"
    assert replacement_action("ask", old, "One two three four five six.", "stop") == "propose"
    for finish in ("length", None, "load"):  # cut at the limit, stopped / failed, anything else
        assert replacement_action("auto", old, "One two", finish) is None
    assert replacement_action("auto", old, "   ", "stop") is None


def test_a_much_shorter_answer_is_never_applied_unseen() -> None:
    old = "a long paragraph of the user's own words that should not vanish"
    assert replacement_action("auto", old, "a long paragraph", "stop") == "propose"
    assert replacement_action("auto", old, old.upper(), "stop") == "apply"
    assert replacement_action("readonly", old, "short", "stop") == "show"


@pytest.mark.parametrize(
    ("reply", "original", "clean"),
    [
        ("Sure! Here is the corrected text:\n\nThe cat sat.", "", "The cat sat."),
        ("Here's a clearer version:\nIt works.", "", "It works."),
        ("The cat sat.\n\nLet me know if you want more changes!", "", "The cat sat."),
        ("Fixed.\n\nI've corrected the spelling.", "", "Fixed."),
        ("<think>hmm, commas</think>\nThe cat, sat.", "", "The cat, sat."),
        ("```markdown\nThe cat sat.\n```", "", "The cat sat."),
        ("```py\nx = 1\n```", "```py\nx=1\n```", "```py\nx = 1\n```"),  # a block stays a block
        ("Note: keep this\n\nline two", "", "Note: keep this\n\nline two"),  # not a preamble
        ("Here is: the plan", "", "Here is: the plan"),  # one line is the answer itself
    ],
)
def test_clean_reply(reply: str, original: str, clean: str) -> None:
    assert clean_reply(reply, original) == clean


@pytest.fixture
def ai(tmp_path: Path) -> tuple[AiEngine, FakeProvider]:
    v = Vault(tmp_path / "v")
    v.root.mkdir()
    v.create_note("a.md", "# A\nalpha body\n")
    fake = FakeProvider(delay=0)
    engine = AiEngine(
        v, Config(vault=v.root), provider_factory=lambda _c: fake, access_dir=tmp_path / "cfg"
    )
    engine.allow()
    return engine, fake


async def _ask(engine: AiEngine, text: str, **kw: object) -> None:
    out = engine.add_message(text, **kw)  # type: ignore[arg-type]
    reply = engine.start_reply()
    async for _ in engine.answer(reply, out, EditorSnapshot()):
        pass


async def test_a_cut_chat_answer_is_marked_and_never_applied(
    ai: tuple[AiEngine, FakeProvider],
) -> None:
    engine, fake = ai
    fake.reply, fake.finish = "ALPHA", "length"
    await _ask(engine, "shout it", selections=[engine.selection("alpha body", "a.md")])
    reply = engine.turns[-1]
    assert reply.cut and reply.text.endswith(CUT_OFF)
    assert engine.edit_from_reply(reply) is None
    fake.finish = "stop"
    fake.reply = "Sure, here it is:\nALPHA BODY"
    await _ask(engine, "again", selections=[engine.selection("alpha body", "a.md")])
    assert engine.edit_from_reply(engine.turns[-1]) == ("a.md", "alpha body", "ALPHA BODY")


async def test_a_failed_answer_keeps_what_arrived(ai: tuple[AiEngine, FakeProvider]) -> None:
    engine, fake = ai
    fake.reply, fake.fail_after = "one two three four", 2
    out = engine.add_message("count")
    reply = engine.start_reply()
    with pytest.raises(ProviderError):
        async for _ in engine.answer(reply, out, EditorSnapshot()):
            pass
    engine.failed(reply, "Ollama stopped")
    assert reply.text.startswith("one two") and "*(stopped: Ollama stopped)*" in reply.text
    assert reply.cut and not reply.error
    empty = engine.start_reply()
    engine.failed(empty, "no answer")
    assert empty.error and empty.text == "no answer"


async def test_the_answer_may_use_what_the_prompt_leaves(
    ai: tuple[AiEngine, FakeProvider],
) -> None:
    engine, fake = ai
    await _ask(engine, "hi")
    assert fake.options is not None and fake.options.num_ctx == 8192
    assert fake.options.num_predict is not None and 7000 < fake.options.num_predict < 8192


async def test_one_answer_at_a_time(ai: tuple[AiEngine, FakeProvider]) -> None:
    engine, fake = ai
    fake.delay, fake.reply = 0.01, "a b c d e f"
    first = asyncio.create_task(_ask(engine, "long one"))
    await asyncio.sleep(0.02)
    with pytest.raises(ProviderError, match=BUSY[:20]):
        async for _ in engine.stream([]):
            pass
    await first
    assert "".join([p async for p in engine.stream([])])  # free again


async def test_a_selection_too_long_to_rewrite_is_refused(
    ai: tuple[AiEngine, FakeProvider],
) -> None:
    engine, fake = ai
    fake.max_context = 1024
    spec = StreamInsert("Fix it.", source="selection", replace_selection=True)
    long = "word " * 1500
    with pytest.raises(EditTooLongError, match="Select less"):
        await engine.command_messages(spec, path="a.md", text=long, caret=0, selected=long)
    assert not fake.calls  # refused before asking the model
    short = await engine.command_messages(spec, path="a.md", text=long, caret=0, selected="tiny")
    assert "tiny" in short[-1].content
