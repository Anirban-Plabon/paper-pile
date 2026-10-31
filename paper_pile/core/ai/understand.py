"""What a typed request about selected text means (PLAN §4.31): one small model call that reads
the request with the text and decides — does the user want the text changed or something told
to them; for a change, whether it says enough to act on (if not: a question and options for the
user to pick from), and how far a change may reach. It replaces
deciding by first words and word lists (``ask_route.route_by_words``, ``intent.edit_intent``),
which stay only as the fallback when the model cannot be asked. No UI imports.

The rules describe the kinds of request, not phrases: an unseen wording must land the same way
(``tools/ai_eval/intent.py`` measures that on paraphrases).
"""

import logging
from dataclasses import dataclass
from typing import Any, Literal

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.guards import Size
from paper_pile.core.ai.intent import Intent
from paper_pile.core.ai.provider import ChatMessage, ProviderError

log = logging.getLogger("paper_pile.ai.understand")

Want = Literal["change", "answer"]
SELECTION_CHARS = 1500  # of the selected text shown with the request
MAX_OPTIONS = 4

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "want": {"type": "string", "enum": ["change", "answer"]},
        "complete": {"type": "boolean"},
        "question": {"type": "string", "maxLength": 90},
        "options": {
            "type": "array",
            "items": {"type": "string", "maxLength": 70},
            "maxItems": MAX_OPTIONS,
        },
        "reach": {"type": "string", "enum": ["selection", "note"]},
        "size": {"type": "string", "enum": ["small", "medium", "large"]},
        "adds": {"type": "boolean"},
        "new_form": {"type": "boolean"},
    },
    "required": ["want", "complete", "question", "options", "reach", "size", "adds", "new_form"],
}

RULES = """\
A user selected text in a markdown note and typed a request about it. Work out what they mean.

want:
- "change": the user wants the selected text itself to end up different in the note — any \
rewording, more or fewer words, more depth or detail on what it says, another tone, style, \
language or format, something added into it, corrected, restructured or removed. The text is \
the user's own writing: an instruction to do something with it or to write more about its \
subject is a change, even when it is one word.
- "answer": the user wants something told or shown to them while the note stays as it is — \
a question (what, why, is it, does it…), or a request to explain, summarize, judge or check \
it for them to read.

complete (only for "change"; true for "answer"):
- true when the request says what the result should be, or when there is one obvious way to \
do it.
- false when the request names a kind of change but leaves open a choice between different \
results — opposite ones, or different options of the same kind — that the user must make and \
the text does not settle. Do not guess for the user.
question and options (only when complete is false): a short question asking that choice, and \
3-4 concrete, different choices that fit this text, each a complete short request in the \
user's language. Otherwise "" and [].

reach: "selection" when only the selected text should change; "note" when the request asks \
for other parts of the note too, or other places must change to stay consistent (a count, a \
list, an introduction that names what was changed).
size: how much of the text changes — "small": a few words (typos, grammar, punctuation); \
"medium": some sentences; "large": most of it is rewritten or much is added.
adds: true when new content is put in (not only the existing text changed).
new_form: true when the text should take another markdown form (a list, a table, a quote, \
headings, a code block…) rather than stay as it is shaped.

Reply only with the JSON object."""


@dataclass(frozen=True, slots=True)
class Understood:
    want: Want
    complete: bool
    question: str
    options: tuple[str, ...]
    reach: Literal["selection", "note"]
    size: Size
    adds: bool
    new_form: bool = False

    def intent(self) -> Intent:
        """The edit pipeline's intent (scope, size, adds, a new form) from this."""
        scope: Literal["text", "note"] = "text" if self.reach == "selection" else "note"
        return Intent(scope, self.size, self.adds, self.new_form)


def messages(request: str, selected: str) -> list[ChatMessage]:
    shown = selected if len(selected) <= SELECTION_CHARS else selected[:SELECTION_CHARS] + " …"
    return [
        ChatMessage("system", RULES),
        ChatMessage("user", f"Selected text:\n<<<\n{shown}\n>>>\n\nRequest: {request}"),
    ]


def parse(data: dict[str, Any] | None) -> Understood | None:
    """The model's JSON as :class:`Understood`; None when it is unusable. An incomplete change
    without options to offer is acted on as it is (asking with nothing to pick helps no one)."""
    if not data or data.get("want") not in ("change", "answer"):
        return None
    want: Want = data["want"]
    options = tuple(
        dict.fromkeys(str(o).strip() for o in data.get("options") or [] if str(o).strip())
    )[:MAX_OPTIONS]
    # an open choice needs at least two options to pick from; else it is acted on as it is
    complete = want == "answer" or bool(data.get("complete", True)) or len(options) < 2
    reach: Literal["selection", "note"] = "note" if data.get("reach") == "note" else "selection"
    sizes: dict[str, Size] = {"small": "small", "medium": "medium", "large": "large"}
    size = sizes.get(str(data.get("size")), "medium")
    return Understood(
        want,
        complete,
        "" if complete else str(data.get("question") or "").strip(),
        () if complete else options,
        reach,
        size,
        bool(data.get("adds")),
        bool(data.get("new_form")),
    )


async def understand(engine: AiEngine, request: str, selected: str) -> Understood | None:
    """``request`` about ``selected``, understood by the model; None when it cannot say (the
    caller falls back to the first-words rules)."""
    try:
        data = await engine.ask_json(messages(request, selected), SCHEMA, max_answer=300)
    except ProviderError:
        log.info("could not ask the model what the request means", exc_info=True)
        return None
    found = parse(data)
    log.debug("%r → %r", request, found)
    return found
