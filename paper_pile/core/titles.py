"""The ``title`` property: every note gets its name as the title in its front matter, and a
rename keeps it in step unless the user wrote a different title.

Pure text functions; the UI decides when to call them. A note whose front matter cannot be read
is left alone.
"""

import re

from paper_pile.core.parser import front_matter
from paper_pile.core.rewrite import Edit

_FM = re.compile(r"\A---[ \t]*\r?\n(?:[^\n]*\n)*?---[ \t]*(?:\r?\n|\Z)")
_TITLE_LINE = re.compile(r"^title:[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_PLAIN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ .()\-]*$")
_RESERVED = {"null", "true", "false", "yes", "no", "on", "off", "~"}


def note_name(path: str) -> str:
    """The note's name: its file name without the extension."""
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def format_title(name: str) -> str:
    """``name`` as a YAML scalar (quoted only when plain YAML would read it differently)."""
    numeric = re.fullmatch(r"[-+]?[\d.]+(e[-+]?\d+)?", name, re.IGNORECASE)
    if (
        _PLAIN.match(name)
        and name.strip() == name
        and name.lower() not in _RESERVED
        and not numeric
    ):
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def with_title(text: str, name: str) -> str | None:
    """``text`` with ``title: name`` added to its front matter, or ``None`` if it needs none."""
    nl = _newline(text)
    line = f"title: {format_title(name)}{nl}"
    block = _FM.match(text)
    if block is None:
        return f"---{nl}{line}---{nl}{nl if not text.strip() else ''}{text}"
    fm = front_matter(text)
    if fm is None or fm.error or "title" in fm.data:
        return None
    first = text.index("\n") + 1
    return text[:first] + line + text[first:]


def retitle_edit(text: str, old: str, new: str) -> Edit | None:
    """The edit that renames the title ``old`` to ``new``; ``None`` if the title is not ``old``
    (the user wrote their own) or cannot be found as a one-line value."""
    block = _FM.match(text)
    fm = front_matter(text) if block else None
    if block is None or fm is None or fm.error:
        return None
    current = fm.data.get("title")
    if not isinstance(current, str) or current.strip() != old:
        return None
    head = text[: block.end()]
    m = _TITLE_LINE.search(head)
    if m is None:
        return None
    return Edit(m.start(1), m.end(1), format_title(new))
