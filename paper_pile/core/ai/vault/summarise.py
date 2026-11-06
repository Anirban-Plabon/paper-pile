"""Summaries of one note or of many (PLAN_vault_agent §3.2 ``summarise``, P30.22).

- One note: its text (cut at the budget) is summarised directly.
- Many notes — map-reduce: the map step is the note cards (``cards.py``; a current card
  costs no model call, a missing one is made once and kept), each card under its label; the
  reduce step writes the summary with citations. More cards than one call holds are merged
  in rounds: groups → partial summaries that keep the labels → one final summary.

Citations keep their global labels through every round, so the final check covers them.
No UI imports.
"""

from collections.abc import Callable, Sequence

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.provider import ChatMessage
from paper_pile.core.ai.vault.cards import CardMaker
from paper_pile.core.ai.vault.cite import CITE_RULES, Source, check, sources_block
from paper_pile.core.ai.vault.reply import Reply
from paper_pile.core.ai.vault.results import ResultSet
from paper_pile.core.ai.vault.tools import ToolError, VaultTools

ONE_NOTE_CHARS = 12000
GROUP = 12  # cards per reduce call
Progress = Callable[[str, int, int], None]

SUMMARY_RULES = """\
You summarise the user's own notes, given below as numbered sources. Write what the user \
asked for, in the language of the request, in markdown: the main points first, grouped by \
theme when there are several notes, no padding. Use only what the sources say.
"""

MERGE_RULES = """\
You merge partial summaries of the user's notes into one summary. Keep every source label \
([n]) that a kept point carries, drop repeats, group by theme, main points first. Use only \
what the partial summaries say. Write in markdown, in the language of the request.
"""


async def _text(engine: AiEngine, msgs: list[ChatMessage]) -> str:
    return "".join([p async for p in engine.stream(msgs, think=False)]).strip()


def _msgs(rules: str, sources: Sequence[Source], request: str) -> list[ChatMessage]:
    return [
        ChatMessage("system", rules + "\n" + CITE_RULES),
        ChatMessage("user", f"{sources_block(sources)}\n\nRequest: {request}"),
    ]


async def summarise_note(
    engine: AiEngine, tools: VaultTools, path: str, request: str, results: ResultSet
) -> Reply:
    """A summary of one note, cited against its own text."""
    try:
        part = tools.read(path, max_chars=ONE_NOTE_CHARS)
    except ToolError as e:
        return Reply(str(e), results)
    src = Source(1, part.path, part.title, "", part.start, part.end, part.text, part.text[:80])
    text = await _text(engine, _msgs(SUMMARY_RULES, [src], request))
    checked = check(text, [src])
    notices = ["The note is long; the summary covers its first part."] if part.cut else []
    return Reply(checked.text, results, [src], checked, notices=notices)


async def summarise_many(
    engine: AiEngine,
    maker: CardMaker,
    request: str,
    results: ResultSet,
    *,
    group: int = GROUP,
    on_progress: Progress | None = None,
) -> Reply:
    """A summary across the notes of ``results`` (sure ones; unsure ones only when there are
    no sure ones), from their note cards."""
    items = results.sure() or results.maybe()
    paths = [i.path for i in items]
    cards = await maker.ensure(
        paths, on_progress=(lambda d, t: on_progress("cards", d, t)) if on_progress else None
    )
    titles = {i.path: i.title for i in items}
    # a card is a summary, not the note's text: no anchor (a citation opens the note's top)
    sources = [
        Source(n, p, titles[p], "", 1, 1, cards[p].summary)
        for n, p in enumerate([p for p in paths if p in cards], 1)
    ]
    missing = [titles[p] for p in paths if p not in cards]
    notices = [f"Left out (could not be read): {', '.join(missing)}"] if missing else []
    if not sources:
        return Reply("I could not read any of these notes.", results, notices=notices)
    if len(sources) <= group:
        text = await _text(engine, _msgs(SUMMARY_RULES, sources, request))
    else:
        partials: list[str] = []
        groups = [sources[i : i + group] for i in range(0, len(sources), group)]
        for k, part in enumerate(groups, 1):
            partials.append(await _text(engine, _msgs(SUMMARY_RULES, part, request)))
            if on_progress:
                on_progress("merge", k, len(groups) + 1)
        body = "\n\n".join(f"Partial summary {k}:\n{p}" for k, p in enumerate(partials, 1))
        text = await _text(
            engine,
            [
                ChatMessage("system", MERGE_RULES),
                ChatMessage("user", f"{body}\n\nRequest: {request}"),
            ],
        )
        if on_progress:
            on_progress("merge", len(groups) + 1, len(groups) + 1)
    checked = check(text, sources)
    return Reply(checked.text, results, sources, checked, notices=notices)
