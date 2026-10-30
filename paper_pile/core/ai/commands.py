"""The one list of AI commands (PLAN §4.28): the editor's slash menu, the command palette, the
Ask box's ``/`` list and the chat box's ``/`` list are all built from it, so the titles, order,
icons and what each command does are the same everywhere.

Three kinds: a *change* rewrites the target and is shown as a diff (Rewrite, Change tone); an
*answer* is written into the note under the target (Summarize, Explain, Outline); a *shown*
answer stays in the mini chat / chat until the user pushes it into the note (Translate). Words
the user types after a command are its instruction. The target is the selection, or the whole
note's body when nothing is selected (``command_target``). No UI imports here.
"""

from dataclasses import dataclass
from typing import Literal

from paper_pile.core.commands import StreamInsert
from paper_pile.core.parser import body_start

Kind = Literal["change", "answer", "shown"]
KEEP = (
    "Keep its meaning, its facts, its language and its markdown formatting unless asked otherwise."
)


@dataclass(frozen=True, slots=True)
class AiCommand:
    id: str
    title: str
    subtitle: str
    icon: str
    kind: Kind
    aliases: tuple[str, ...]
    task: str  # what the model is asked; ``{words}`` is the user's instruction
    default: str  # the instruction when the user gave none and picked no option
    suggest: str  # what kind of options the AI suggests when the command runs without words
    fallback: tuple[tuple[str, str], ...]  # (label, group) shown when the model gives none

    def instruction(self, words: str = "") -> str:
        """The task with the user's ``words`` (or the default) filled in."""
        given = " ".join(words.split()).rstrip(".")
        return self.task.format(words=given or self.default)

    def request(self, words: str = "") -> str:
        """The task in a few words, for an edit plan ("Rewrite: make it shorter")."""
        given = " ".join(words.split()).rstrip(".")
        return f"{self.title}: {given or self.default}"

    def spec(self, words: str = "") -> StreamInsert:
        """How the editor runs it: a change replaces the target (as a diff), an answer or a
        shown answer goes with the target as its text."""
        if self.kind == "change":
            return StreamInsert(self.instruction(words), source="selection", replace_selection=True)
        return StreamInsert(self.instruction(words), source="auto", lead="\n\n")


AI_COMMANDS: tuple[AiCommand, ...] = (
    AiCommand(
        "ai-rewrite",
        "Rewrite",
        "Change the text as you ask",
        "pen-line",
        "change",
        ("rephrase", "reword", "improve", "modify", "edit", "fix", "grammar", "shorter", "longer"),
        "Rewrite the text below: {words}. " + KEEP + " Write only the new text.",
        "make it read clearly and well",
        'ways to improve this text, each naming what it fixes (e.g. "Fix 3 grammar errors", '
        '"Split the long second sentence", "Make it shorter")',
        (
            ("Fix grammar and spelling", "fix"),
            ("Make it shorter", "length"),
            ("Make it clearer", "clarity"),
            ("Make it more detailed", "length"),
        ),
    ),
    AiCommand(
        "ai-tone",
        "Change tone",
        "Formal, casual, friendly…",
        "message-circle",
        "change",
        ("tone", "formal", "casual", "friendly", "style", "voice"),
        "Rewrite the text below in this tone: {words}. " + KEEP + " Write only the new text.",
        "clear and friendly",
        'tones that would suit this text and its readers (e.g. "More formal", "Friendly", '
        '"Confident")',
        (("More formal", "tone"), ("Friendly", "tone"), ("Confident", "tone"), ("Casual", "tone")),
    ),
    AiCommand(
        "ai-summarize",
        "Summarize",
        "Written under the text",
        "scroll-text",
        "answer",
        ("summary", "tldr", "short version"),
        "Summarize the text below: {words}. Keep the language of the text.",
        "concisely, as a short paragraph, or a few bullet points if it has several parts",
        'kinds of summary that fit this text (e.g. "One line", "Key decisions", "3 bullet points")',
        (
            ("One line", "length"),
            ("A short paragraph", "length"),
            ("Key points as bullets", "structure"),
        ),
    ),
    AiCommand(
        "ai-explain",
        "Explain",
        "Written under the text",
        "brain",
        "answer",
        ("what does this mean", "meaning", "clarify"),
        "Explain the text below: {words}. Keep the language of the text.",
        "clearly and briefly, for someone who knows the subject less well",
        'things in this text worth explaining, or ways to explain it (e.g. "Explain the term '
        'X", "In simple words", "With an example")',
        (
            ("In simple words", "clarity"),
            ("With an example", "content"),
            ("Step by step", "structure"),
        ),
    ),
    AiCommand(
        "ai-outline",
        "Outline",
        "Written under the text",
        "list-tree",
        "answer",
        ("outline", "structure", "key points", "bullets"),
        "Write an outline of the text below: {words}. Keep the language of the text.",
        "as a nested bullet list of its main points",
        'kinds of outline that fit this text (e.g. "Main points only", "Nested by section", '
        '"As questions")',
        (
            ("Main points only", "length"),
            ("Nested, two levels", "structure"),
            ("As a numbered list", "structure"),
        ),
    ),
    AiCommand(
        "ai-translate",
        "Translate",
        "Shown first; you choose to put it in",
        "languages",
        "shown",
        ("translate", "language", "translation"),
        "Translate the text below into {words}. Keep the markdown exactly: headings, lists, "
        "tables, links, images. Do not translate code, URLs, #tags, math, or the note name "
        "inside [[ ]] (only the text after |). Reply with only the translation.",
        "English",
        "languages the user likely wants this text in (not the language it is written in)",
        (
            ("English", "language"),
            ("Spanish", "language"),
            ("French", "language"),
            ("German", "language"),
            ("Bengali", "language"),
        ),
    ),
)
_BY_ID = {c.id: c for c in AI_COMMANDS}
AI_COMMAND_IDS = tuple(_BY_ID)


def ai_command(command_id: str) -> AiCommand | None:
    return _BY_ID.get(command_id)


@dataclass(frozen=True, slots=True)
class Target:
    """What a command acts on: ``text[start:end]`` of the note; ``whole`` when nothing was
    selected (the body: the front matter is never part of it)."""

    start: int
    end: int
    text: str
    whole: bool


def command_target(note: str, selection: tuple[int, int] | None) -> Target | None:
    """The selection when there is a non-blank one, else the note's body; None for an empty
    note."""
    if selection is not None:
        a, b = sorted(selection)
        if note[a:b].strip():
            return Target(a, b, note[a:b], whole=False)
    start = body_start(note)
    if not note[start:].strip():
        return None
    return Target(start, len(note), note[start:], whole=True)


# ---- typed in the chat box: ``/tone more formal`` (PLAN §4.28) ------------------------------


def command_name(cmd: AiCommand) -> str:
    """What is typed after ``/`` in the chat box: ``rewrite``, ``tone``, ``summarize``…"""
    return cmd.id.removeprefix("ai-")


def search_commands(query: str) -> list[AiCommand]:
    """The commands for ``/query`` in the chat box, in the one list's order: all of them for an
    empty query, else those whose name, title or an alias starts with it."""
    q = query.strip().lower()
    if not q:
        return list(AI_COMMANDS)
    return [
        c
        for c in AI_COMMANDS
        if any(w.startswith(q) for w in (command_name(c), *c.title.lower().split(), *c.aliases))
    ]


def parse_command(text: str) -> tuple[AiCommand, str] | None:
    """``/tone more formal`` → (Change tone, "more formal"); a partial name (``/to``) is the
    first command it matches; None when the text is not an AI command (``/compact``, words)."""
    if not text.startswith("/"):
        return None
    head, _, words = text[1:].partition(" ")
    head = head.strip().lower()
    if not head:
        return None
    exact = next((c for c in AI_COMMANDS if command_name(c) == head), None)
    found = exact or next(iter(search_commands(head)), None)
    return (found, words.strip()) if found is not None else None
