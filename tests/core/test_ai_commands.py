"""P25.1: the one list of AI commands and what they act on (PLAN §4.28)."""

from paper_pile.core.ai.commands import AI_COMMAND_IDS, ai_command, command_target

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
