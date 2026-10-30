"""P25.1: the one list of AI commands and what they act on (PLAN §4.28)."""

import paper_pile.core.commands_builtin  # noqa: F401  (registers the slash commands)
from paper_pile.core.ai.commands import (
    AI_COMMAND_IDS,
    ai_command,
    command_name,
    command_target,
    parse_command,
    search_commands,
)
from paper_pile.core.ai.selection_ask import box_commands
from paper_pile.core.commands import REGISTRY, CommandContext

NOTE = "---\ntitle: T\n---\n# Head\n\nbody text\n"


def test_the_list_and_its_kinds() -> None:
    assert AI_COMMAND_IDS == (
        "ai-rewrite",
        "ai-tone",
        "ai-summarize",
        "ai-explain",
        "ai-outline",
        "ai-translate",
    )
    kinds = {i: c.kind for i in AI_COMMAND_IDS if (c := ai_command(i))}
    assert kinds["ai-rewrite"] == kinds["ai-tone"] == "change"
    assert kinds["ai-summarize"] == kinds["ai-explain"] == kinds["ai-outline"] == "answer"
    assert kinds["ai-translate"] == "shown"  # the user pushes it into the note
    assert ai_command("ai-fix") is None and ai_command("ai-continue") is None


def test_words_are_the_instruction_else_the_default() -> None:
    tone = ai_command("ai-tone")
    assert tone is not None
    assert "in this tone: more formal." in tone.instruction("  more   formal. ")
    assert "in this tone: clear and friendly." in tone.instruction("")
    translate = ai_command("ai-translate")
    assert translate is not None and "into Bengali." in translate.instruction("Bengali")


def test_changes_replace_and_answers_insert() -> None:
    rewrite, summary = ai_command("ai-rewrite"), ai_command("ai-summarize")
    assert rewrite is not None and summary is not None
    assert rewrite.spec("shorter").replace_selection
    spec = summary.spec()
    assert not spec.replace_selection and spec.source == "auto" and spec.lead == "\n\n"


def test_the_target_is_the_selection_else_the_body() -> None:
    at = NOTE.index("body")
    sel = command_target(NOTE, (at + 4, at))  # backwards is fine
    assert sel is not None and (sel.text, sel.whole) == ("body", False)
    whole = command_target(NOTE, None)
    assert whole is not None and whole.whole and whole.text == "# Head\n\nbody text\n"
    assert command_target(NOTE, (at, at)) == whole  # an empty selection: the whole note
    assert command_target("---\na: 1\n---\n  \n", None) is None  # nothing to act on


def test_chat_box_command_names() -> None:
    assert [command_name(c) for c in search_commands("")] == [
        "rewrite",
        "tone",
        "summarize",
        "explain",
        "outline",
        "translate",
    ]
    assert [c.id for c in search_commands("formal")] == ["ai-tone"]
    found = parse_command("/tone  more formal ")
    assert found is not None and found[0].id == "ai-tone" and found[1] == "more formal"
    found = parse_command("/sum")
    assert found is not None and found[0].id == "ai-summarize" and found[1] == ""
    assert parse_command("/compact") is None and parse_command("hello") is None
    assert parse_command("/") is None


def test_every_ai_place_lists_the_same_commands_in_the_same_order() -> None:
    """The editor's slash menu, the Ask box's / list and the chat box's / list (the palette is
    built from AI_COMMANDS directly) — PLAN §4.28."""
    ctx = CommandContext("a.md", "Some text.", 0, selection=(0, 10))
    slash = [c.id for g in REGISTRY.search("", ctx) for c in g.commands if c.id in AI_COMMAND_IDS]
    box = [c.id for c in box_commands("", ctx) if c.id in AI_COMMAND_IDS]
    chat = [c.id for c in search_commands("")]
    assert slash == box == chat == list(AI_COMMAND_IDS)
