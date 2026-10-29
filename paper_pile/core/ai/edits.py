"""How an AI answer may change a note (PLAN §4.26): one decision for every entry point, and the
answer turned into the text that replaces the user's.

Two kinds of change exist. *Inserts* (Continue writing, Summarize, Explain, Ask…, the chat's
*Insert into note*) add text at the caret: they stream in and are one undo step, with a
"before AI" version kept first. *Replacements* (Fix grammar, the selection bar's Edit, Rewrite,
the chat's *Apply to note*) change the user's own text: they are shown as a diff, applied at once
only in *Apply at once* mode, and never made from an answer that did not finish. *Read-only*
refuses inserts and shows replacements without Accept. No UI imports here.
"""

import re
from typing import Literal

EditMode = Literal["ask", "auto", "readonly"]
EditKind = Literal["insert", "replace"]
EditAction = Literal["stream", "propose", "apply", "show", "refuse"]

FINISHED = "stop"  # the finish reason of an answer the model ended itself
SHORT_SHARE = 0.5  # a replacement shorter than this share of the original is never auto-applied
REPLY_MARGIN = 1.25  # a rewrite may be this much longer than the text it replaces
REPLY_EXTRA = 64  # tokens on top, for a short selection


class EditTooLongError(Exception):
    """The text to change does not fit in the model's window with its answer; fit to show."""


def edit_mode(value: object) -> EditMode:
    """``ai.edits`` as a mode (anything unknown is the safe default, ask)."""
    if value == "auto" or value == "readonly":
        return value
    return "ask"


def edit_action(mode: EditMode, kind: EditKind) -> EditAction:
    """What an AI change of ``kind`` does under ``mode`` (the table in the module docstring)."""
    if kind == "insert":
        return "refuse" if mode == "readonly" else "stream"
    replace: dict[EditMode, EditAction] = {"ask": "propose", "auto": "apply", "readonly": "show"}
    return replace[mode]


def replacement_action(mode: EditMode, old: str, new: str, finish: str | None) -> EditAction | None:
    """What to do with a finished replacement ``new`` for ``old``: None when there must be no
    edit at all (the answer was cut off, stopped or failed, or is empty). A much shorter answer
    is shown as a diff even in *Apply at once* mode (it may have lost the end of the text)."""
    if finish != FINISHED or not new.strip():
        return None
    action = edit_action(mode, "replace")
    if action == "apply" and len(new.strip()) < len(old.strip()) * SHORT_SHARE:
        return "propose"
    return action


def reply_room(text_tokens: int) -> int:
    """Tokens a rewrite of a text of ``text_tokens`` needs for its answer."""
    return int(text_tokens * REPLY_MARGIN) + REPLY_EXTRA


_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_PREAMBLE = re.compile(
    r"(?:sure|okay|ok|certainly|of course|absolutely|here(?:'s| is| are)|below is|this is)\b"
    r"[^\n]{0,120}:\s*$",
    re.IGNORECASE,
)
_CLOSING = re.compile(
    r"(?:let me know|i hope|hope this|feel free|i(?:'ve| have) (?:fixed|corrected|changed|made|"
    r"kept|rewritten)|(?:the )?changes? (?:made|include)|note:)",
    re.IGNORECASE,
)
_FENCE = re.compile(r"(`{3,}|~{3,})[\w-]*\n(.*?)\n?\1\s*", re.DOTALL)


def clean_reply(text: str, original: str = "") -> str:
    """The replacement text in a model's answer: its reasoning (``<think>…</think>``), one
    leading "Here is the corrected text:" line, one closing "Let me know…" paragraph and one
    code fence around everything removed. A fence is kept when ``original`` itself was one."""
    out = _THINK.sub("", text).strip()
    first, _, rest = out.partition("\n")
    if rest.strip() and _PREAMBLE.fullmatch(first.strip()):
        out = rest.strip()
    head, sep, last = out.rpartition("\n\n")
    if sep and head.strip() and _CLOSING.match(last.strip()):
        out = head.strip()
    fenced = _FENCE.fullmatch(out)
    if fenced and not _FENCE.fullmatch(original.strip()):
        out = fenced.group(2)
    return out
