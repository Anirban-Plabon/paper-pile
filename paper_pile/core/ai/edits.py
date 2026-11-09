"""How an AI answer may change a note (PLAN §4.26): one decision for every entry point, and the
answer turned into the text that replaces the user's.

Two kinds of change exist. *Inserts* (Summarize, Explain, Outline, Ask…, the chat's
*Insert into note*) add text at the caret: they stream in and are one undo step, with a
"before AI" version kept first. *Replacements* (Rewrite, Change tone, an Ask box rewrite,
the chat's *Apply to note*) change the user's own text: they are shown as a diff in the note
(*Review in the note*), applied at once only in *Apply at once* mode, and never made from an
answer that did not finish. The chat's own edits follow the same mode (PLAN §4.32; *Read-only*
was removed then — a saved ``readonly`` reads as review). No UI imports here.
"""

from typing import Literal

from paper_pile.core.ai.cleanup import clean_reply as clean_reply  # moved there (P26.6)

EditMode = Literal["ask", "auto"]  # ask = Review in the note
EditKind = Literal["insert", "replace"]
EditAction = Literal["stream", "propose", "apply", "show", "refuse"]

FINISHED = "stop"  # the finish reason of an answer the model ended itself
SHORT_SHARE = 0.5  # a replacement shorter than this share of the original is never auto-applied
REPLY_MARGIN = 1.25  # a rewrite may be this much longer than the text it replaces
REPLY_EXTRA = 64  # tokens on top, for a short selection


class EditTooLongError(Exception):
    """The text to change does not fit in the model's window with its answer; fit to show."""


def edit_mode(value: object) -> EditMode:
    """``ai.edits`` as a mode (anything unknown — the old ``readonly`` too — is the safe
    default, review)."""
    return "auto" if value == "auto" else "ask"


def edit_action(mode: EditMode, kind: EditKind) -> EditAction:
    """What an AI change of ``kind`` does under ``mode`` (the table in the module docstring)."""
    if kind == "insert":
        return "stream"
    return "apply" if mode == "auto" else "propose"


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
