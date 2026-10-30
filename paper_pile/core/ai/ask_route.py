"""The Ask box under a selection (PLAN §4.27): is a message a request to change the selected
text, or a question about it? Clear first words decide at once (no model call); anything else
("put it in a quote", "bold the names", "this as a table") is left to the model, which only
answers "edit" or "answer". No UI imports here.
"""

import logging
import re
from typing import Literal

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.provider import ChatMessage, ProviderError

log = logging.getLogger("paper_pile.ai.route")

Route = Literal["edit", "answer"]

# words in front of the request that do not change what it asks for
_POLITE = frozenset({"please", "pls", "plz", "kindly", "can", "could", "would", "will", "you", "u"})
# a message starting with one of these asks for the text to be changed
_EDIT_VERBS = frozenset(
    {
        "rewrite",
        "rephrase",
        "reword",
        "modify",
        "change",
        "edit",
        "fix",
        "correct",
        "improve",
        "polish",
        "shorten",
        "condense",
        "lengthen",
        "expand",
        "simplify",
        "translate",
        "convert",
        "turn",
        "format",
        "reformat",
        "restructure",
        "replace",
        "make",
        "proofread",
    }
)
# a message starting with one of these asks about the text
_QUESTION_WORDS = frozenset(
    {
        "what",
        "what's",
        "whats",
        "why",
        "how",
        "who",
        "whom",
        "whose",
        "when",
        "where",
        "which",
        "is",
        "are",
        "was",
        "were",
        "does",
        "did",
        "explain",
        "summarize",
        "summarise",
        "describe",
        "define",
        "tell",
        "meaning",
    }
)
_WRITE_OBJECTS = frozenset({"it", "this", "that", "the"})  # "write it as…", not "write a poem"
_WORD = re.compile(r"[\w']+")
SELECTION_CHARS = 1500  # of the selected text shown to the model when it decides

ROUTE_SCHEMA = {
    "type": "object",
    "properties": {"action": {"type": "string", "enum": ["edit", "answer"]}},
    "required": ["action"],
}
ROUTE_RULES = (
    "The user selected text in a markdown note and typed a request about it. Decide what they "
    "want.\n"
    '"edit": the selected text should be changed in the note — reworded, reformatted (quote, '
    "list, table, bold, heading, code block…), added to, shortened, split, moved, or removed.\n"
    '"answer": they want information shown to them — an explanation, a summary, an opinion, '
    "facts, or new text that is not meant to replace the selection.\n"
    'Reply only with JSON: {"action": "edit"} or {"action": "answer"}.'
)


def route_by_words(message: str) -> Route | None:
    """ "edit" when the first word after polite ones is an edit verb (or "write it / this …"),
    "answer" when it is a question word, None when the words alone do not tell."""
    words = [w.lower() for w in _WORD.findall(message)]
    while words and words[0] in _POLITE:
        words.pop(0)
    if not words:
        return "answer"
    if words[0] in _EDIT_VERBS:
        return "edit"
    if words[0] == "write" and len(words) > 1 and words[1] in _WRITE_OBJECTS:
        return "edit"
    if words[0] in _QUESTION_WORDS:
        return "answer"
    return None


def route_messages(message: str, selected: str) -> list[ChatMessage]:
    """The model's task when the words do not decide."""
    shown = selected if len(selected) <= SELECTION_CHARS else selected[:SELECTION_CHARS] + " …"
    return [
        ChatMessage("system", ROUTE_RULES),
        ChatMessage("user", f"Selected text:\n<<<\n{shown}\n>>>\n\nRequest: {message}"),
    ]


async def route(engine: AiEngine, message: str, selected: str) -> Route:
    """Edit or answer ``message`` about ``selected``: by its words, else by the model. A model
    that fails or answers nonsense gives "answer" (it never changes the note)."""
    found = route_by_words(message)
    if found is not None:
        return found
    try:
        data = await engine.ask_json(route_messages(message, selected), ROUTE_SCHEMA, max_answer=32)
    except ProviderError:
        log.info("routing failed; answering instead", exc_info=True)
        return "answer"
    action = data.get("action") if data else None
    log.debug("model routed %r → %r", message, action)
    return "edit" if action == "edit" else "answer"
