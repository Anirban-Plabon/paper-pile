"""Link extraction, resolution, and rewriting on rename/move.

So far: the policy for links that leave the app (P2.4) and the shape of a ``[[wikilink]]``
(P3.1). Note-to-note resolution, backlinks and rename rewriting arrive with the rest of P3.
"""

import posixpath
import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

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


# ---- note-to-note resolution (P3.3) -----------------------------------------------------------

_NOTE_EXT = re.compile(r"\.(md|txt)$", re.IGNORECASE)


def norm_name(name: str) -> str:
    """Comparison key of a note name: trimmed, lower-case, without ``.md`` / ``.txt``.

    The editor repeats this to style links to missing notes (``tools/editor_src/livepreview.js``).
    """
    return _NOTE_EXT.sub("", name.strip().lower())


def _folder(path: str) -> str:
    return posixpath.dirname(path)


def resolve_wikilink(note: str, source: str, paths: Iterable[str]) -> str | None:
    """The note path a ``[[note]]`` points at, or ``None``.

    ``note`` is a vault-relative path or a bare name, with or without extension, in any case.
    A name starting with ``/`` is an exact vault path. A name written with a ``/`` prefers the
    exact vault path over a trailing-part match (``folder/note``). When several notes match, the
    one in the source note's folder wins, then the shallowest, then ``.md`` over ``.txt``, then
    alphabetical order. ``[[#heading]]`` (empty ``note``) points at the source note itself.
    """
    if not note.strip():
        return source
    key = norm_name(note).strip("/")
    explicit_ext = bool(_NOTE_EXT.search(note.strip()))
    full: list[str] = []
    partial: list[str] = []
    for path in paths:
        stem = norm_name(path)
        if stem == key:
            full.append(path)
        elif stem.endswith("/" + key):
            partial.append(path)
    # a bare name competes across all folders; a path (`a/b`) prefers the exact full path
    if note.strip().startswith("/"):
        partial = []  # a leading slash means the exact vault path
    pool = full + partial if "/" not in key else (full or partial)
    if explicit_ext:
        exact = [p for p in pool if p.lower().endswith(note.strip().lower().lstrip("/"))]
        pool = exact or pool
    if not pool:
        return None
    here = _folder(source)
    return min(pool, key=lambda p: (_folder(p) != here, p.count("/"), p.endswith(".txt"), p))


def resolve_md_link(href: str, source: str, paths: Collection[str]) -> str | None:
    """The note a relative markdown link ``[t](../other.md#part)`` points at, or ``None``."""
    target = unquote(href.strip()).split("#", 1)[0].split("?", 1)[0]
    if not target or target.startswith("/") or _SCHEME_LIKE.match(target):
        return None
    joined = posixpath.normpath(posixpath.join(_folder(source), target))
    return joined if joined in paths else None


_SCHEME_LIKE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def link_keys(paths: Iterable[str]) -> list[str]:
    """Every name a wikilink may use for these notes (see :func:`norm_name`), for the editor to
    tell links to existing notes from links to missing ones."""
    keys: set[str] = set()
    for path in paths:
        parts = norm_name(path).split("/")
        keys.update("/".join(parts[i:]) for i in range(len(parts)))
    return sorted(keys)


def new_note_path(note: str, source: str) -> str | None:
    """Where ``[[note]]`` should be created when it does not exist: next to the source note, or
    under the vault root when ``note`` is written as a path. ``None`` for an unusable name."""
    name = note.strip().strip("/")
    if not name or any(part in {"", ".", ".."} or part.startswith(".") for part in name.split("/")):
        return None
    if not _NOTE_EXT.search(name):
        name += ".md"
    return name if "/" in note.strip() else posixpath.join(_folder(source), name)


def link_snippet(text: str, line: int, width: int = 140) -> str:
    """The one line of a note that holds a link, tidied for a list: list/quote/heading markers
    dropped, whitespace collapsed, cut to ``width`` characters."""
    lines = text.splitlines()
    raw = lines[line - 1] if 1 <= line <= len(lines) else ""
    raw = re.sub(r"^\s*(?:>\s*)*(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+|#{1,6}\s+)?", "", raw)
    clean = " ".join(raw.split())
    return clean if len(clean) <= width else clean[: width - 1].rstrip() + "…"


def wikilink_forms(target: str, *, ext: bool = False) -> list[str]:
    """Ways to write a wikilink to ``target``, shortest first: the bare name, then more and more
    of its folder path, and last the exact vault path (``/folder/name``). ``ext`` keeps the file
    extension."""
    stem = _NOTE_EXT.sub("", target)
    tail = target[len(stem) :] if ext else ""
    parts = stem.split("/")
    forms = ["/".join(parts[i:]) + tail for i in range(len(parts) - 1, -1, -1)]
    return [*forms, "/" + stem + tail]


def wikilink_to(target: str, source: str, paths: Collection[str]) -> str:
    """The shortest name that, written in ``[[...]]`` inside ``source``, opens ``target`` and
    names only that note, so the link keeps working if a same-named note is added elsewhere."""
    forms = wikilink_forms(target)
    path_list = list(paths)

    def names_only_target(form: str) -> bool:
        if form.startswith("/"):
            return True  # an exact path
        key = norm_name(form).strip("/")
        return sum(1 for p in path_list if (n := norm_name(p)) == key or n.endswith("/" + key)) == 1

    working = [f for f in forms if resolve_wikilink(f, source, path_list) == target]
    return next((f for f in working if names_only_target(f)), working[0] if working else forms[-1])
