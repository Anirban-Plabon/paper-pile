"""Turn a command's :data:`~paper_pile.core.commands.Action` into the exact text edit to make.

The editor tells us where the typed ``/query`` is (``start``..``end``); we answer with edits in
code-point offsets of the *current* text, so the browser only has to apply them. All the rules
about what a block marker is live here, not in JS.
"""

import re
from dataclasses import dataclass

from paper_pile.core.commands import (
    Action,
    Insert,
    OpenNote,
    OpenPicker,
    ReplaceLinePrefix,
    ReplaceSelection,
    StreamInsert,
)


@dataclass(frozen=True, slots=True)
class TextChange:
    start: int
    end: int
    insert: str


@dataclass(frozen=True, slots=True)
class TextEdit:
    changes: tuple[TextChange, ...]
    cursor: int  # caret offset in the text *after* the changes


# Leading block markers of a line: quotes, headings, bullets, numbers, task boxes (any mix).
_INDENT = re.compile(r"[ \t]*")
_MARKER = re.compile(r"(?:(?:#{1,6}|[-*+]|\d{1,9}[.)]|>)[ \t]+(?:\[[ xX]\][ \t]+)?|>)+")


def remove_range(start: int, end: int) -> TextEdit:
    """Delete the typed ``/query`` and leave the caret where it was."""
    return TextEdit((TextChange(start, end, ""),), start)


def resolve(action: Action, text: str, start: int, end: int) -> TextEdit | None:
    """The edit for ``action`` where ``text[start:end]`` is the typed ``/query``.

    Actions that are not text edits (``OpenNote``, ``OpenPicker``, ``StreamInsert``) return
    ``None``: the caller removes the ``/query`` itself and then does what they ask.
    """
    if isinstance(action, Insert):
        cursor = start + (
            len(action.text) if action.cursor_offset is None else action.cursor_offset
        )
        return TextEdit((TextChange(start, end, action.text),), cursor)
    if isinstance(action, ReplaceSelection):
        return TextEdit((TextChange(start, end, action.text),), start + len(action.text))
    if isinstance(action, ReplaceLinePrefix):
        return _replace_line_prefix(action.prefix, text, start, end, action.blank_after)
    if isinstance(action, OpenNote | OpenPicker | StreamInsert):
        return None
    raise TypeError(f"unknown action: {action!r}")


def _replace_line_prefix(
    prefix: str, text: str, start: int, end: int, blank_after: bool = False
) -> TextEdit:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    before, after = text[line_start:start], text[end:line_end]
    line = before + after  # the line without the typed /query
    indent = _INDENT.match(line)
    indent_len = indent.end() if indent else 0
    marker = _MARKER.match(line, indent_len)
    marker_len = marker.end() - indent_len if marker else 0
    old_marker = line[indent_len : indent_len + marker_len]
    rest = line[indent_len + marker_len :]
    new_marker = (
        "" if old_marker.rstrip() == prefix.rstrip() and prefix else prefix
    )  # same again: toggle off
    new_line = line[:indent_len] + new_marker + rest
    if blank_after and _needs_blank_after(text, line_end):
        new_line += "\n"
    caret_in_rest = max(0, len(before) - indent_len - marker_len)
    cursor = line_start + indent_len + len(new_marker) + min(caret_in_rest, len(rest))
    return TextEdit((TextChange(line_start, line_end, new_line),), cursor)


_CONTINUES = re.compile(r"^[ \t]*(?:[-*+]|\d{1,9}[.)]|>)(?:\s|$)|^[ \t]+\S")


def _needs_blank_after(text: str, line_end: int) -> bool:
    """Should an empty line be added after the line ending at ``line_end``? Yes at the end of the
    note and before a line that is not itself part of a list or quote."""
    if line_end >= len(text):
        return True
    next_line = text[line_end + 1 :].split("\n", 1)[0]
    return bool(next_line.strip()) and not _CONTINUES.match(next_line)
