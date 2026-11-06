"""What a chat message asks of the vault (PLAN_vault_agent §3, §5.1; P30.13 / P30.15): one
small JSON call turns the message into ordered steps — each an action on a target (folders,
tags, dates, named notes, links, the last result, or a topic to search for) — or says that the
message does not need the vault at all. Dates are only labelled here; ``dates.py`` computes
them. Names are resolved and ambiguity asked about afterwards (``plan.py``). No UI imports.

The rules describe kinds of request, never phrases (CLAUDE.md gotcha, memory "AI intent must
generalize"): an unseen wording must land the same way.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Literal

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.provider import ChatMessage, ProviderError
from paper_pile.core.ai.vault.meta import QUERIES
from paper_pile.core.ai.vault.scope import Scope, scope_from_json

log = logging.getLogger("paper_pile.ai.vault.understand")

Action = Literal[
    "locate", "answer", "summarise", "extract", "meta", "compare", "write", "edit", "other"
]
ACTIONS: tuple[Action, ...] = (
    "locate",
    "answer",
    "summarise",
    "extract",
    "meta",
    "compare",
    "write",
    "edit",
    "other",
)
MAX_STEPS = 5
MAX_TERMS = 12
MAX_OPTIONS = 4
SHOWN_FOLDERS = 40  # folder names shown to the model
SHOWN_TAGS = 30

_STRINGS = {"type": "array", "items": {"type": "string"}}
_DATES = {
    "type": "object",
    "properties": {
        "this": {"type": "string", "enum": ["day", "week", "month", "year"]},
        "last": {"type": "string", "enum": ["day", "week", "month", "year"]},
        "past": {"type": "integer"},
        "unit": {"type": "string", "enum": ["day", "week", "month", "year"]},
        "year": {"type": "integer"},
        "month": {"type": "integer"},
        "day": {"type": "integer"},
        "from": {"type": "string"},
        "to": {"type": "string"},
    },
}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "needs_vault": {"type": "boolean"},
        "steps": {
            "type": "array",
            "maxItems": MAX_STEPS,
            "items": {
                "type": "object",
                # every field required and in this order: a constrained model skips optional
                # fields, and decides the target before it writes the topic and terms
                "properties": {
                    "action": {"type": "string", "enum": list(ACTIONS)},
                    "meta": {"type": "string", "enum": ["", *QUERIES]},
                    "folders": _STRINGS,
                    "tags": _STRINGS,
                    "notes": _STRINGS,
                    "linked_from": _STRINGS,
                    "links_to": _STRINGS,
                    "dates": _DATES,
                    "date_kind": {"type": "string", "enum": ["content", "edited", "any"]},
                    "from_result": {"type": "string"},
                    "topic": {"type": "string", "maxLength": 120},
                    "terms": {**_STRINGS, "maxItems": MAX_TERMS},
                    "detail": {"type": "string", "maxLength": 300},
                    "depends_on": {"type": "integer"},
                },
                "required": [
                    "action",
                    "meta",
                    "folders",
                    "tags",
                    "notes",
                    "linked_from",
                    "links_to",
                    "dates",
                    "date_kind",
                    "from_result",
                    "topic",
                    "terms",
                    "detail",
                    "depends_on",
                ],
            },
        },
        "question": {"type": "string", "maxLength": 120},
        "options": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_OPTIONS},
    },
    "required": ["needs_vault", "steps", "question", "options"],
}

RULES = """\
You read a message a user typed in the chat of their markdown note app and work out what it \
asks of their notes (the vault). Answer with JSON only.

needs_vault: true when answering needs notes the user did not attach — finding, reading, \
counting, summarising, comparing or changing notes in the vault. False for anything that can \
be answered without looking through their notes (general questions, chatting, a question \
about only the open or attached note). When false, give no steps.

steps: what to do, in the order the user wants it; one step per separate thing asked. A \
message that asks two things gives two steps. A later step that works on what an earlier one \
found sets depends_on to that step's number (0 = the first step); else depends_on is -1.

action, one per step:
- "locate": the user wants to know which notes, or where something is written.
- "answer": a question to be answered from what the notes say.
- "summarise": a summary of one note or of many notes.
- "extract": a list or table of particular facts gathered from many notes.
- "meta": facts about the notes themselves, not their content.

meta ("" unless action is "meta"), the one that fits — each list also says how many it holds, \
so "how many …" takes the list that matches what is counted:
- "count": how many notes (and words) there are in the target, nothing else asked;
- "folders": the folders and how many notes each holds;
- "recent": notes by when they were last changed (with dates: changed in that period);
- "no_links": notes with no links to or from other notes;
- "largest": the longest notes;
- "untagged": notes without any tag;
- "tags": the tags in use and how many notes carry each.
- "compare": how notes differ, or how something changed over time across notes.
- "write": a new note made from what was found.
- "edit": existing notes to be changed (add, remove, correct or rewrite something in them).
- "other": anything else about the vault.

target fields of a step — they narrow which notes the step works on, so a wrong one hides \
the notes the user wants. Set a field only when the message itself limits the notes that \
way: it names the folder, tag, note, link or period, or calls the notes by a kind that one \
folder holds. Never guess where notes on a topic might be kept — a topic alone gives no \
folder and no tag; it is searched for with terms. Fill every field the message does give, \
also when the same thing is said in detail; [] / {} / "" otherwise:
- folders, tags, notes: the folders, tags and note names the message limits the step to. \
Use the lists of the vault's folders and tags below to write them as they exist (a folder \
the user calls by a kind of note, like their daily notes or meetings, is the folder that \
holds them).
- linked_from / links_to: a note whose links to follow, or whose backlinks to take.
- dates: when the message limits the notes by a date or a period, label it, never compute \
days: {"this": unit} for the current day/week/month/year, {"last": unit} for the previous \
one, {"past": n, "unit": unit} for the last n units up to today, {"year", "month", "day"} \
for a calendar date or period (leave out the parts not said), {"from", "to"} as YYYY-MM-DD \
for explicit dates. date_kind: "edited" when it is about when notes were changed, \
"content" when it is about what the notes are dated or about (meetings, daily notes, \
events), "any" when unclear.
- from_result: when the step works on the previous answer's notes listed below: "all", or \
their numbers like "2,3". Empty otherwise.

topic: the subject in a few words ("" when the step has none, e.g. a count of all notes).
terms: what to search the notes for, so that notes about the topic are found even when they \
never use the user's words: the topic's own words first, then 6 to 11 more that a note on \
the same subject would likely contain — other names for it, the narrower ideas, methods, \
examples and well-known people or organisations it is known for, other spellings. Every \
term must be about the topic itself, not just share a word with it. [] when the step needs \
no search: a named note, a whole folder or tag, a date range alone, or a meta question.
detail: what exactly to do, in the user's language: the question to answer, the facts to \
gather, the change to make. Short.

question / options: only when the message leaves a choice open that the user must make and \
no reasonable reading covers it: one short question and two to four options. Otherwise \
question is "" and options are [].
"""


@dataclass(frozen=True, slots=True)
class Step:
    action: Action
    topic: str = ""
    terms: tuple[str, ...] = ()
    scope: Scope = field(default_factory=Scope)
    from_result: str = ""
    meta: str = ""
    detail: str = ""
    depends_on: int = -1


@dataclass(frozen=True, slots=True)
class VaultRequest:
    needs_vault: bool
    steps: tuple[Step, ...] = ()
    question: str = ""  # an open choice the user must make ("" when clear)
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RequestContext:
    """What the model is shown with the message."""

    today: date
    folders: Sequence[str] = ()  # readable folders, vault-relative
    tags: Sequence[str] = ()  # most used first
    open_note: str = ""  # its title
    last_result: str = ""  # ResultSet.compact()
    scoped: Sequence[str] = ()  # @folder/ / @vault scopes the message carries ("" = vault)
    memory: str = ""  # the vault memory file (memory.py), the user's own description


def messages(request: str, ctx: RequestContext) -> list[ChatMessage]:
    parts = [f"Today is {ctx.today.isoformat()} ({ctx.today.strftime('%A')})."]
    if ctx.memory:
        parts.append(f"About this vault (written by the user):\n{ctx.memory}")
    if ctx.folders:
        parts.append("Folders: " + ", ".join(list(ctx.folders)[:SHOWN_FOLDERS]))
    if ctx.tags:
        parts.append("Tags: " + ", ".join("#" + t for t in list(ctx.tags)[:SHOWN_TAGS]))
    if ctx.open_note:
        parts.append(f"Open note: {ctx.open_note}")
    if ctx.scoped:
        names = ["the whole vault" if s == "" else f"folder {s.rstrip('/')}" for s in ctx.scoped]
        parts.append("The user pointed the message at: " + ", ".join(names))
    if ctx.last_result:
        parts.append(ctx.last_result)
    parts.append(f"Message: {request}")
    return [ChatMessage("system", RULES), ChatMessage("user", "\n\n".join(parts))]


def _strs(raw: object, most: int) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(dict.fromkeys(s.strip() for s in raw if isinstance(s, str) and s.strip()))[:most]


_RESULT_PICK = re.compile(r"^\d+(?:\s*,\s*\d+)*$")


def _from_result(raw: object) -> str:
    """``"all"`` or ``"2,3"``; anything else (``"-1"``, ``"none"``, prose) is no pick."""
    text = str(raw or "").strip().lower()
    if text == "all":
        return "all"
    return ",".join(p.strip() for p in text.split(",")) if _RESULT_PICK.match(text) else ""


def _step(raw: object, index: int, today: date) -> Step | None:
    if not isinstance(raw, dict) or raw.get("action") not in ACTIONS:
        return None
    depends = raw.get("depends_on")
    ok_dep = isinstance(depends, int) and not isinstance(depends, bool) and 0 <= depends < index
    action: Action = raw["action"]
    meta = ""
    if action == "meta":  # a meta name on another action is noise
        meta = str(raw["meta"]) if raw.get("meta") in QUERIES else "count"
    return Step(
        action=action,
        topic=str(raw.get("topic") or "").strip(),
        terms=_strs(raw.get("terms"), MAX_TERMS),
        scope=scope_from_json(raw, today),
        # a step that works on an earlier step's notes does not also take the last answer's
        from_result="" if ok_dep else _from_result(raw.get("from_result")),
        meta=meta,
        detail=str(raw.get("detail") or "").strip(),
        depends_on=depends if ok_dep and isinstance(depends, int) else -1,
    )


def parse(data: dict[str, Any] | None, today: date) -> VaultRequest | None:
    """The model's JSON as a :class:`VaultRequest`; None when unusable. Malformed steps are
    dropped; a vault request whose steps all fail is unusable. A choice offers at least two
    options or is not asked."""
    if not data or not isinstance(data.get("needs_vault"), bool):
        return None
    if not data["needs_vault"]:
        return VaultRequest(False)
    raw_steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    steps: list[Step] = []
    for raw in list(raw_steps or [])[:MAX_STEPS]:
        step = _step(raw, len(steps), today)
        if step is not None:
            steps.append(step)
    if not steps:
        return None
    options = _strs(data.get("options"), MAX_OPTIONS)
    question = str(data.get("question") or "").strip()
    if not question or len(options) < 2:
        question, options = "", ()
    return VaultRequest(True, tuple(steps), question, options)


async def understand_request(
    engine: AiEngine, request: str, ctx: RequestContext
) -> VaultRequest | None:
    """``request`` understood by the model; None when it cannot say (the chat then answers
    as it does without the vault agent)."""
    try:
        data = await engine.ask_json(messages(request, ctx), SCHEMA, max_answer=700)
    except ProviderError:
        log.info("could not ask the model what the vault request means", exc_info=True)
        return None
    found = parse(data, ctx.today)
    if found is not None and not ctx.last_result:  # no earlier answer to take notes from
        found = replace(found, steps=tuple(replace(s, from_result="") for s in found.steps))
    log.debug("%r → %r", request, found)
    return found
