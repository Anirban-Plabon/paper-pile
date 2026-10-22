"""Tags (PLAN §4.16): inline ``#tag`` and the ``tags`` property in front matter.

The inline rule here is the reference for the editor grammar (``tools/editor_src/tag.js``); both
are checked against ``tests/fixtures/tag_cases.json``. Tags compare case-insensitively and a tag
also matches its nested children (``a`` matches ``a/b``).
"""

import unicodedata
from collections.abc import Iterable
from typing import Any

EXTRA_CHARS = "_-/"


def is_tag_char(c: str) -> bool:
    """Letters, combining marks (Bengali vowel signs…), digits, ``_``, ``-`` and ``/``."""
    return c in EXTRA_CHARS or unicodedata.category(c)[0] in "LMN"


def tag_body(text: str, start: int) -> str:
    """The tag that starts right after a ``#`` at ``start - 1`` in ``text`` ("" if none): the run
    of tag characters, trailing ``/`` dropped, not starting with ``/``, not digits only."""
    end = start
    while end < len(text) and is_tag_char(text[end]):
        end += 1
    body = text[start:end].rstrip("/")
    if not body or body.startswith("/"):
        return ""
    if all(unicodedata.category(c)[0] == "N" for c in body):
        return ""
    return body


def starts_tag(text: str, pos: int) -> bool:
    """Can a tag start at the ``#`` at ``pos``: first in the text or after whitespace."""
    return text[pos] == "#" and (pos == 0 or text[pos - 1].isspace())


def norm_tag(tag: str) -> str:
    """The form tags are compared in: no leading ``#``, no outer slashes, lower case."""
    return tag.strip().lstrip("#").strip("/").casefold()


def clean_tag(raw: str) -> str:
    """A tag as written in the ``tags`` property, or "" if it is not a usable tag."""
    raw = raw.strip().strip("\"'").lstrip("#")
    return raw if raw and tag_body(raw, 0) == raw.rstrip("/") else ""


def property_tags(data: dict[str, Any]) -> list[str]:
    """Tags from parsed front matter: ``tags`` as a list, or a string split on commas/spaces."""
    value = data.get("tags")
    if isinstance(value, str):
        items: Iterable[Any] = value.replace(",", " ").split()
    elif isinstance(value, list):
        items = value
    else:
        return []
    found = (clean_tag(str(item)) for item in items if item is not None)
    return [tag for tag in found if tag]


def unique(tags: Iterable[str]) -> list[str]:
    """Tags in first-seen order, one per normalised form."""
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags:
        key = norm_tag(tag)
        if key and key not in seen:
            seen.add(key)
            out.append(tag)
    return out


def matches(tag: str, wanted: str) -> bool:
    """Does ``tag`` belong under ``wanted`` (the same tag or one nested in it)?"""
    t, w = norm_tag(tag), norm_tag(wanted)
    return t == w or t.startswith(w + "/")
