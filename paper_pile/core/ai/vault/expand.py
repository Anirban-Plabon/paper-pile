"""A second search round from the notes the judge kept (PLAN_vault_agent §4, P30.16): the
first terms come from the model's idea of the topic, which can be off ("social business"
read as social media); the notes confirmed as on-topic show what the user's own notes call
it. One small JSON call asks for further terms drawn from those notes; candidates found with
them are judged like the first ones. No word lists anywhere — the notes are the evidence.
"""

import logging
from collections.abc import Sequence
from typing import Any

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.provider import ChatMessage, ProviderError
from paper_pile.core.ai.vault.judge import Judged

log = logging.getLogger("paper_pile.ai.vault.expand")

MAX_MORE = 8
SHOWN_NOTES = 6
NOTE_CHARS = 300

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "terms": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_MORE},
    },
    "required": ["terms"],
}

RULES = """\
A user is looking for all their notes on a topic. Some notes were already confirmed to be \
about it; they show the words this user's notes use for it. Give up to 8 further search \
terms — words or short phrases — that other notes on the same topic would likely contain: \
names, ideas, methods, places and people that these notes connect with the topic. Not the \
terms already searched. Every term must belong to the topic as these notes show it, not \
just to one note's side details. Answer with JSON only.
"""


def messages(topic: str, kept: Sequence[Judged], used: Sequence[str]) -> list[ChatMessage]:
    notes = []
    for j in list(kept)[:SHOWN_NOTES]:
        snippet = " ".join(j.candidate.snippet.split())[:NOTE_CHARS]
        notes.append(f"- {j.candidate.title}: {snippet}")
    body = (
        f"Topic: {topic}\n\nAlready searched: {', '.join(used)}\n\n"
        "Notes confirmed to be about it:\n" + "\n".join(notes)
    )
    return [ChatMessage("system", RULES), ChatMessage("user", body)]


def parse(data: dict[str, Any] | None, used: Sequence[str]) -> list[str]:
    raw = data.get("terms") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    seen = {u.casefold() for u in used}
    out: list[str] = []
    for t in raw:
        if not isinstance(t, str):
            continue
        term = " ".join(t.split())
        if term and term.casefold() not in seen:
            seen.add(term.casefold())
            out.append(term)
    return out[:MAX_MORE]


async def more_terms(
    engine: AiEngine, topic: str, kept: Sequence[Judged], used: Sequence[str]
) -> list[str]:
    """Further search terms from the notes judged "yes"; [] when there are none or the model
    cannot say (the first round's result stands)."""
    sure = [j for j in kept if j.relevance == "yes"]
    if not sure:
        return []
    try:
        data = await engine.ask_json(messages(topic, sure, used), SCHEMA, max_answer=200)
    except ProviderError:
        log.info("could not ask for more search terms", exc_info=True)
        return []
    return parse(data, used)
