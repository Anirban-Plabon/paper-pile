"""Answering a question from the found notes, with citations (PLAN_vault_agent §3.2
``answer``, §7.1; P30.21). The most relevant section of each note is sent under a label;
the answer cites the labels; the citations are checked before the answer is final. No UI
imports.
"""

from collections.abc import Callable, Sequence

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.provider import ChatMessage
from paper_pile.core.ai.vault.cite import CITE_RULES, Source, check, make_sources, sources_block
from paper_pile.core.ai.vault.reply import Reply
from paper_pile.core.ai.vault.results import ResultItem, ResultSet
from paper_pile.core.ai.vault.tools import ToolError, VaultTools, best_hit_section

BUDGET_CHARS = 12000  # of note text sent with one question
PART_CHARS = 3000  # of one note
WHOLE_CHARS = 1500  # a note this short is sent whole

ANSWER_RULES = """\
You answer a question from the user's own notes, given below as numbered sources. Use only \
what the sources say; when they do not hold the answer, say so plainly instead of guessing. \
Answer in the language of the question, short and to the point, in markdown.
"""


Part = tuple[str, str, str, int, int, str]  # path, title, heading, start, end, text


def _part(tools: VaultTools, item: ResultItem, words: Sequence[str]) -> Part | None:
    """``(path, title, heading, start, end, text)`` of the part of ``item`` to send."""
    try:
        whole = tools.read(item.path, max_chars=PART_CHARS)
    except ToolError:
        return None
    if len(whole.text) <= WHOLE_CHARS and not whole.cut:
        return (item.path, item.title, "", whole.start, whole.end, whole.text)
    heading = item.heading
    if not heading:
        lines = whole.text  # look for the section in what fits
        sec = best_hit_section(lines, words)
        heading = sec.heading if sec else ""
    if heading:
        try:
            part = tools.read(item.path, heading, max_chars=PART_CHARS)
            return (item.path, item.title, part.heading, part.start, part.end, part.text)
        except ToolError:
            pass
    return (item.path, item.title, "", whole.start, whole.end, whole.text)


def pick_sources(
    tools: VaultTools, results: ResultSet, words: Sequence[str], budget: int = BUDGET_CHARS
) -> list[Source]:
    """Labelled parts of the found notes — sure ones first, unsure ones only when there are
    no sure ones — while they fit ``budget``."""
    items = results.sure() or results.maybe()
    parts: list[Part] = []
    used = 0
    for item in items:
        part = _part(tools, item, words)
        if part is None:
            continue
        size = len(part[5])
        if parts and used + size > budget:
            break
        parts.append(part)
        used += size
    return make_sources(parts)


def messages(question: str, sources: Sequence[Source]) -> list[ChatMessage]:
    return [
        ChatMessage("system", ANSWER_RULES + "\n" + CITE_RULES),
        ChatMessage("user", f"{sources_block(sources)}\n\nQuestion: {question}"),
    ]


async def answer(
    engine: AiEngine,
    tools: VaultTools,
    question: str,
    results: ResultSet,
    words: Sequence[str] = (),
    *,
    on_text: Callable[[str], None] | None = None,
) -> Reply:
    """The answer to ``question`` from ``results``. ``on_text`` gets the answer as it grows
    (raw, before the check); the reply holds the checked text. Raises ProviderError like
    ``engine.stream``."""
    sources = pick_sources(tools, results, words)
    if not sources:
        return Reply("I found no notes that answer this.", results)
    parts: list[str] = []
    async for piece in engine.stream(messages(question, sources), think=False):
        parts.append(piece)
        if on_text is not None:
            on_text("".join(parts))
    checked = check("".join(parts).strip(), sources)
    return Reply(checked.text, results, sources, checked)
