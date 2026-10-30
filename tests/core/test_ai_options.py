"""AI-suggested options for a command run without words (PLAN §4.28, AI_EDITS §8)."""

from pathlib import Path

import pytest

from paper_pile.core.ai.access import AccessDeniedError
from paper_pile.core.ai.commands import AI_COMMANDS, ai_command
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.fake import FakeProvider
from paper_pile.core.ai.options import (
    GROUPS,
    MAX_OPTIONS,
    OPTIONS_SCHEMA,
    TARGET_CHARS,
    Option,
    clean_options,
    fallback_options,
    options_groups,
    options_instruction,
    suggest_options,
    tick,
)
from paper_pile.core.config import Config
from paper_pile.core.vault import Vault

TONE = ai_command("ai-tone")
assert TONE is not None


@pytest.fixture
def setup(tmp_path: Path) -> tuple[AiEngine, FakeProvider]:
    vault = Vault(tmp_path / "v")
    vault.root.mkdir()
    fake = FakeProvider(delay=0)
    ai = AiEngine(vault, Config(vault=vault.root), provider_factory=lambda _c: fake)
    ai.allow()
    return ai, fake


async def test_model_options_are_used(setup: tuple[AiEngine, FakeProvider]) -> None:
    ai, fake = setup
    fake.script = [
        '{"options": [{"label": "More formal", "group": "tone"}, '
        '{"label": "Friendly", "group": "tone"}, {"label": "1. Confident.", "group": "x"}]}'
    ]
    found = await suggest_options(ai, TONE, path="a.md", note="Hi there.", target="Hi there.")
    assert found == [Option("More formal", "tone"), Option("Friendly", "tone"), Option("Confident")]
    assert fake.options is not None and fake.options.schema == OPTIONS_SCHEMA
    sent = fake.calls[0]
    assert "Change tone" in sent[0].content and "Hi there." in sent[-1].content


@pytest.mark.parametrize(
    "reply", ["not json", "{}", '{"options": "x"}', '{"options": ["only one", "two"]}']
)
async def test_bad_answers_give_the_fixed_list(
    setup: tuple[AiEngine, FakeProvider], reply: str
) -> None:
    ai, fake = setup
    fake.script = [reply]
    found = await suggest_options(ai, TONE, path="a.md", note="x", target="x")
    assert found == fallback_options(TONE)


async def test_failing_model_gives_the_fixed_list(setup: tuple[AiEngine, FakeProvider]) -> None:
    ai, fake = setup
    fake.fail_calls = 1
    found = await suggest_options(ai, TONE, path="a.md", note="x", target="x")
    assert found == fallback_options(TONE)


async def test_note_the_ai_may_not_read(setup: tuple[AiEngine, FakeProvider]) -> None:
    ai, fake = setup
    with pytest.raises(AccessDeniedError):
        await suggest_options(ai, TONE, path="a.md", note="---\nai: false\n---\nx", target="x")
    assert fake.calls == []


async def test_long_target_is_cut(setup: tuple[AiEngine, FakeProvider]) -> None:
    ai, fake = setup
    fake.script = ['{"options": ["a", "b", "c"]}']  # plain strings count as labels
    long = "word " * 2000
    await suggest_options(ai, TONE, path="a.md", note=long, target=long)
    assert len(fake.calls[0][-1].content) < TARGET_CHARS + 50


def test_clean_options() -> None:
    raw = ["  - Shorter.", {"label": "shorter"}, 3, "", "x " * 50, "a", "b", "c", "d"]
    found = clean_options(raw)
    assert found[0] == Option("Shorter") and len(found) == MAX_OPTIONS
    assert found[1].label.endswith("…") and len(found[1].label) <= 61
    assert clean_options("nope") == []


def test_every_command_has_options() -> None:
    for cmd in AI_COMMANDS:
        assert cmd.suggest and 3 <= len(cmd.fallback) <= MAX_OPTIONS
        assert all(group in GROUPS for _label, group in cmd.fallback)


def test_options_instruction() -> None:
    picked = [Option("Shorter", "length"), Option("More formal.", "tone")]
    assert options_instruction(picked, " keep the list ") == (
        "Do all of these: 1) Shorter 2) More formal 3) keep the list"
    )
    assert options_instruction(picked[:1]) == "Shorter"
    assert options_instruction([], "") == ""
    assert options_groups(picked) == ("length", "tone")


def test_single_choice_groups() -> None:
    """Case 14 of the eval (AI_EDITS §10): two length options — only the last stays ticked."""
    short, long_, fix = (
        Option("Shorter", "length"),
        Option("Longer", "length"),
        Option("Fix", "fix"),
    )
    ticked = tick(tick(tick([], fix), short), long_)
    assert ticked == [fix, long_]
    assert tick(ticked, long_) == [fix]  # a click on a ticked one unticks it
    assert tick([Option("Formal", "tone")], Option("Casual", "tone")) == [Option("Casual", "tone")]
    a, b = Option("Add an example", "content"), Option("Add a source", "content")
    assert tick([a], b) == [a, b]  # other groups combine
