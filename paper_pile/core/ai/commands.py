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
