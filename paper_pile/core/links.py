"""Link extraction, resolution, and rewriting on rename/move.

So far: the policy for links that leave the app (P2.4) and the shape of a ``[[wikilink]]``
(P3.1). Note-to-note resolution, backlinks and rename rewriting arrive with the rest of P3.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# Only these schemes may be opened from a note. Everything else (javascript:, file:, data:, ...)
# is refused, because a note can contain anything, including text pasted from a chatbot.
EXTERNAL_SCHEMES = frozenset({"http", "https", "mailto"})
_CONTROL = re.compile(r"[\x00-\x1f\x7f\s]")


def external_url(href: str) -> str | None:
    """The URL to open in the system browser for ``href``, or ``None`` if it must not be opened.

    ``www.example.org`` (a bare GFM autolink) gets ``https://``. Relative paths, note links and
    anything with an unsafe scheme return ``None``.
    """
    href = href.strip()
    if not href or _CONTROL.search(href):
        return None
    if href.lower().startswith("www."):
        href = "https://" + href
    parts = urlsplit(href)
    if parts.scheme.lower() not in EXTERNAL_SCHEMES:
        return None
    if parts.scheme.lower() in {"http", "https"} and not parts.netloc:
        return None
    return href


@dataclass(frozen=True, slots=True)
class WikiTarget:
    """What is inside ``[[...]]``: ``[[note#heading|alias]]``. Any part may be empty, but never
    both ``note`` and ``heading`` (``[[#heading]]`` points into the current note)."""

    note: str
    heading: str
    alias: str

    @property
    def text(self) -> str:
        """What a reader sees: the alias, else ``note > heading`` / ``note`` / ``heading``."""
        if self.alias:
            return self.alias
        if self.note and self.heading:
            return f"{self.note} > {self.heading}"
        return self.note or self.heading


def parse_wikilink(inner: str) -> WikiTarget | None:
    """Split the inside of ``[[...]]``. ``None`` if there is nothing to point at.

    The first ``|`` starts the alias (which may contain more ``|``); the first ``#`` before it
    starts the heading (which may contain more ``#``). Parts are trimmed. The editor grammar
    (``tools/editor_src/wikilink.js``) repeats these rules and is checked against the same fixture.
    """
    target, bar, alias = inner.partition("|")
    note, _hash, heading = target.partition("#")
    parsed = WikiTarget(note.strip(), heading.strip(), alias.strip() if bar else "")
    return parsed if parsed.note or parsed.heading else None
