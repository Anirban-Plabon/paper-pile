"""AI-suggested options (PLAN §4.28, ``docs/AI_EDITS.md`` §8): an AI command run without words
asks the model for 3–5 short options that fit the target ("Fix 3 grammar errors", "More
formal", "One line"), each with a group; the user ticks some (and may add their own) and they
run as one instruction. ``length``, ``tone`` and ``language`` are single-choice groups; the
ticked groups feed the edit intent (``fix`` → small changes, ``content`` → planned). The model
must answer a JSON object of labelled options; anything else gives the command's fixed list, so
the box is never empty. No UI imports here.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from paper_pile.core.ai.commands import AiCommand
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.provider import ChatMessage, ProviderError

log = logging.getLogger("paper_pile.ai.options")

MIN_OPTIONS, MAX_OPTIONS = 3, 5
OPTION_CHARS = 60  # longer options are cut at a word
TARGET_CHARS = 3000  # of the target shown to the model
GROUPS = ("fix", "length", "tone", "clarity", "structure", "content", "language", "other")
SINGLE = frozenset({"length", "tone", "language"})  # ticking one unticks the others

OPTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "options": {
            "type": "array",
            "minItems": MIN_OPTIONS,
            "maxItems": MAX_OPTIONS,
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "maxLength": OPTION_CHARS},
                    "group": {"enum": list(GROUPS)},
                },
                "required": ["label", "group"],
            },
        }
    },
    "required": ["options"],
}
_SPACE = re.compile(r"\s+")
_LEAD = re.compile(r"^(?:[-*•]|\d+[.)])\s*")  # a list marker the model put in front


@dataclass(frozen=True, slots=True)
class Option:
    label: str
    group: str = "other"


def fallback_options(cmd: AiCommand) -> list[Option]:
    return [Option(label, group) for label, group in cmd.fallback]


def options_messages(cmd: AiCommand, target: str) -> list[ChatMessage]:
    """The model's task: suggest options for ``cmd`` on ``target``."""
    shown = target if len(target) <= TARGET_CHARS else target[:TARGET_CHARS] + " …"
    rules = (
        f"The user wants to run the command “{cmd.title}” on a text from their markdown note "
        f"and has not said how. Suggest {MIN_OPTIONS} to {MAX_OPTIONS} {cmd.suggest}. Each "
        f"option is a short instruction of 2 to 7 words in the language of the text, specific "
        f"to this text, different from the others, with its group: fix (errors), length, tone, "
        f"clarity, structure, content (adds or removes information), language, or other. "
        f'Reply only with JSON: {{"options": [{{"label": "...", "group": "..."}}]}}.'
    )
    return [
        ChatMessage("system", rules),
        ChatMessage("user", f"Text:\n<<<\n{shown}\n>>>"),
    ]


def clean_options(raw: object) -> list[Option]:
    """The usable options in the model's ``options`` value: labels trimmed, list markers and end
    dots dropped, long ones cut at a word, duplicates (case-insensitive) dropped, an unknown
    group made ``other``, at most :data:`MAX_OPTIONS`. A plain string counts as a label."""
    if not isinstance(raw, list):
        return []
    out: list[Option] = []
    seen: set[str] = set()
    for item in raw:
        label, group = (item, "other") if isinstance(item, str) else _fields(item)
        text = _LEAD.sub("", _SPACE.sub(" ", label).strip()).rstrip(".").strip()
        if len(text) > OPTION_CHARS:
            text = text[:OPTION_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(Option(text, group if group in GROUPS else "other"))
    return out[:MAX_OPTIONS]


def _fields(item: object) -> tuple[str, str]:
    if not isinstance(item, dict):
        return "", "other"
    label, group = item.get("label"), item.get("group")
    return (label if isinstance(label, str) else ""), (group if isinstance(group, str) else "")


async def suggest_options(
    engine: AiEngine, cmd: AiCommand, *, path: str, note: str, target: str
) -> list[Option]:
    """3–5 options for ``cmd`` on ``target`` (in note ``path``, whole text ``note``): the
    model's, else the command's fixed list. Raises :class:`AccessDeniedError` when the AI may
    not read the note; a failing model or a bad answer gives the fixed list."""
    engine.require_note(path, note)
    try:
        data = await engine.ask_json(options_messages(cmd, target), OPTIONS_SCHEMA, max_answer=320)
    except ProviderError:
        log.info("no options from the model; the fixed list instead", exc_info=True)
        return fallback_options(cmd)
    found = clean_options(data.get("options") if data else None)
    if len(found) < MIN_OPTIONS:
        log.debug("model gave %r; the fixed list instead", data)
        return fallback_options(cmd)
    return found


def tick(ticked: Sequence[Option], option: Option) -> list[Option]:
    """``ticked`` after a click on ``option``: off when it was on; on, and in a single-choice
    group the other options of that group off."""
    if option in ticked:
        return [o for o in ticked if o != option]
    kept = [o for o in ticked if not (option.group in SINGLE and o.group == option.group)]
    return [*kept, option]


def options_instruction(ticked: Sequence[Option], own: str = "") -> str:
    """The ticked options and the user's own words as one instruction: one is said as it is,
    more as "Do all of these: 1) … 2) …"."""
    parts = [o.label.rstrip(".;") for o in ticked if o.label.strip()]
    if own.strip():
        parts.append(own.strip().rstrip(".;"))
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return "Do all of these: " + " ".join(f"{n}) {p}" for n, p in enumerate(parts, 1))


def options_groups(ticked: Sequence[Option]) -> tuple[str, ...]:
    """The groups of the ticked options, for the edit intent."""
    return tuple(dict.fromkeys(o.group for o in ticked))
