"""P26.9: what an AI change asks for, without the model (PLAN §4.29)."""

import pytest

from paper_pile.core.ai.intent import edit_intent


@pytest.mark.parametrize(
    ("command", "words", "groups", "scope", "size", "adds"),
    [
        ("ai-rewrite", "fix grammar", (), "text", "small", False),
        ("ai-rewrite", "fix the spelling and typos", (), "text", "small", False),
        ("ai-rewrite", "make it shorter and more formal", (), "text", "large", False),
        ("ai-rewrite", "", (), "text", "large", False),
        ("ai-tone", "casual", (), "text", "large", False),
        ("ai-rewrite", "", ("fix",), "text", "small", False),
        ("ai-rewrite", "", ("fix", "length"), "text", "large", False),
        ("ai-rewrite", "add option D: Fly.io", (), "note", "medium", True),
        ("ai-rewrite", "", ("content",), "note", "medium", True),
        ("ai-rewrite", "say that the price went up", (), "note", "medium", False),
        ("ai-rewrite", "put it in quote", (), "text", "large", False),
        ("ai-rewrite", "this as a bullet list", (), "text", "large", False),
        ("ai-rewrite", "add a quote from Ana", (), "note", "medium", True),
    ],
)
def test_intent(
    command: str, words: str, groups: tuple[str, ...], scope: str, size: str, adds: bool
) -> None:
    intent = edit_intent(command, words, groups)
    assert (intent.scope, intent.size, intent.adds) == (scope, size, adds)


def test_structure_words() -> None:
    assert edit_intent("ai-rewrite", "add a section about backups").asks_structure
    assert not edit_intent("ai-rewrite", "add backups").asks_structure
