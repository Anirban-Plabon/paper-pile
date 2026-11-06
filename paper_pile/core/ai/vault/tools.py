"""The vault agent's read tools (PLAN_vault_agent §5.3, P30.10): plain Python over the index
and the access-checked note reader, tested without a model. No tool writes, deletes, runs a
program or uses the network; writing tools (``propose_edit``…) only ever produce diffs and come
with M6.

Every note a tool names or returns is one the AI may read: listings come from
:meth:`ScopeResolver.readable`, texts from ``read_note`` (``AiEngine.read_note``: path, file
type and ``ai: false`` checked).
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from paper_pile.core.ai.vault.dates import DayRange
from paper_pile.core.ai.vault.scope import (
    DateKind,
    Scope,
    ScopeResolver,
    match_folders,
    match_names,
    note_folders,
)
from paper_pile.core.index import HeadingRow, Index, NoteRow, query_words
from paper_pile.core.parser import headings

log = logging.getLogger("paper_pile.ai.vault.tools")

READ_CHARS = 6000  # a read's default cap (the agent asks for a section when a note is longer)
SNIPPET_CHARS = 300
SCOPED_FTS_LIMIT = 500  # full-text hits looked at per term when the search is narrowed


class ToolError(Exception):
    """A tool could not do what was asked; the message is shown to the model / the user."""


class NoSuchNoteError(ToolError):
    def __init__(self, name: str) -> None:
        super().__init__(f"No note named {name!r}.")
        self.name = name


class AmbiguousNoteError(ToolError):
    def __init__(self, name: str, candidates: list[str]) -> None:
        super().__init__(f"{name!r} could be: " + ", ".join(candidates))
        self.name = name
        self.candidates = candidates


@dataclass(frozen=True, slots=True)
class Listed:
    path: str
    title: str
    edited: str  # ISO day of the last change
    words: int


@dataclass(frozen=True, slots=True)
class Hit:
    path: str
    title: str
    heading: str  # the section with most of the terms ("" when the note has none)
    snippet: str  # the start of that section, at most SNIPPET_CHARS
    terms: tuple[str, ...]  # which of the searched terms the note matched
    score: float


@dataclass(frozen=True, slots=True)
class Section:
    heading: str  # "" for the text above the first heading / a note without headings
    level: int  # 0 for that text
    start: int  # 1-based first line (the heading's own line)
    end: int  # 1-based last line, included


@dataclass(frozen=True, slots=True)
class ReadResult:
    path: str
    title: str
    heading: str
    start: int
    end: int
    text: str
    cut: bool  # the text was longer than asked for


def _listed(row: NoteRow) -> Listed:
    return Listed(
        row.path, row.title, datetime.fromtimestamp(row.mtime).date().isoformat(), row.words
    )


def sections(text: str) -> list[Section]:
    """The note's sections: each heading's lines up to the next heading of the same or a higher
    level; the text above the first heading is a section with no heading."""
    heads = headings(text)
    total = len(text.split("\n"))
    out: list[Section] = []
    first = heads[0].line if heads else total + 1
    if first > 1:
        out.append(Section("", 0, 1, first - 1))
    for i, head in enumerate(heads):
        end = total
        for later in heads[i + 1 :]:
            if later.level <= head.level:
                end = later.line - 1
                break
        out.append(Section(head.text, head.level, head.line, end))
    return out


def find_section(text: str, heading: str) -> Section | None:
    """The section whose heading is ``heading`` (case and spacing ignored; else the only one
    that contains it); None when there is none or several."""
    key = " ".join(heading.split()).casefold().lstrip("#").strip()
    found = [
        s for s in sections(text) if s.heading and " ".join(s.heading.split()).casefold() == key
    ]
    if not found:
        found = [s for s in sections(text) if s.heading and key in s.heading.casefold()]
    return found[0] if len(found) == 1 else None


def best_hit_section(text: str, words: Sequence[str]) -> Section | None:
    """The ``#``/``##`` section holding most of ``words`` — on a tie the more specific one (a
    ``##`` inside a ``#`` holds the same words); None when none holds any."""
    lines = text.split("\n")
    low_words = [w.casefold() for w in words if w]
    best: Section | None = None
    best_key = (0, 0)
    for sec in sections(text):
        if sec.level > 2:
            continue
        body = "\n".join(lines[sec.start - 1 : sec.end]).casefold()
        key = (sum(body.count(w) for w in low_words), sec.level)
        if key[0] > 0 and key > best_key:
            best, best_key = sec, key
    return best


class VaultTools:
    """The read tools. ``read_note(path)`` returns a note's text or None when the AI may not
    read it; ``resolver`` knows which notes exist and may be listed."""

    def __init__(
        self,
        index: Index,
        resolver: ScopeResolver,
        read_note: Callable[[str], str | None],
        today: Callable[[], date] = date.today,
    ) -> None:
        self.index = index
        self.resolver = resolver
        self._read_note = read_note
        self.today = today

    # ---- names -----------------------------------------------------------------------------

    def note(self, name: str) -> NoteRow:
        """The one readable note ``name`` means; :class:`ToolError` when none or several."""
        rows = self.resolver.readable()
        hits = match_names(name, rows)
        if not hits:
            raise NoSuchNoteError(name)
        if len(hits) > 1:
            raise AmbiguousNoteError(name, hits)
        return next(r for r in rows if r.path == hits[0])

    def _text(self, row: NoteRow) -> str:
        text = self._read_note(row.path)
        if text is None:  # changed to private since the index saw it
            raise NoSuchNoteError(row.path)
        return text

    # ---- listings ----------------------------------------------------------------------------

    def list_folder(self, folder: str = "", recursive: bool = True) -> list[Listed]:
        """Notes in ``folder`` ("" = the whole vault), by path; only its direct notes when not
        ``recursive``."""
        rows = self.resolver.readable()
        name = folder.strip().strip("/")
        base = ""
        if name:
            hits = match_folders(name, note_folders(r.path for r in rows))
            if not hits:
                raise ToolError(f"No folder named {folder!r}.")
            if len(hits) > 1:
                raise ToolError(f"{folder!r} could be: " + ", ".join(hits))
            base = hits[0] + "/"
            rows = [r for r in rows if r.path.startswith(base)]
        if not recursive:
            rows = [r for r in rows if "/" not in r.path[len(base) :]]
        return [_listed(r) for r in rows]

    def in_scope(self, scope: Scope) -> list[Listed]:
        """Notes a whole :class:`Scope` resolves to (ambiguity is the caller's to report)."""
        keep = set(self.resolver.resolve(scope).paths)
        return [_listed(r) for r in self.resolver.readable() if r.path in keep]

    def by_date(self, days: DayRange, kind: DateKind = "content") -> list[Listed]:
        return self.in_scope(Scope(dates=days, date_kind=kind))

    def by_tag(self, tag: str) -> list[Listed]:
        return self.in_scope(Scope(tags=(tag,)))

    def links(self, name: str, direction: str = "out") -> list[Listed]:
        """Notes ``name`` links to (``out``) or that link to it (``in``)."""
        row = self.note(name)
        scope = (
            Scope(linked_from=(row.path,)) if direction == "out" else Scope(links_to=(row.path,))
        )
        return self.in_scope(scope)

    # ---- search --------------------------------------------------------------------------------

    def search(
        self,
        terms: Sequence[str],
        scope: Scope | None = None,
        limit: int = 20,
        *,
        within: set[str] | None = None,
    ) -> list[Hit]:
        """Notes matching any of ``terms`` (each term's words all present), best first: notes
        matching more terms first, then by full-text rank. Inside ``scope`` and / or the paths
        ``within`` when given."""
        terms = [t.strip() for t in terms if t and t.strip()]
        if not terms:
            return []
        narrowed = scope is not None and not scope.empty
        allowed = (
            set(self.resolver.resolve(scope).paths)
            if scope is not None and narrowed
            else {r.path for r in self.resolver.readable()}
        )
        if within is not None:
            allowed &= within
        # a narrowed search looks further down the vault-wide ranking for its few notes
        fts_limit = (
            max(limit * 4, SCOPED_FTS_LIMIT) if narrowed or within is not None else limit * 4
        )
        score: dict[str, float] = {}
        matched: dict[str, list[str]] = {}
        titles: dict[str, str] = {}
        for term in terms:
            for rank, hit in enumerate(self.index.search(term, limit=fts_limit)):
                if hit.path not in allowed:
                    continue
                score[hit.path] = score.get(hit.path, 0.0) + 1.0 + 1.0 / (rank + 2)
                matched.setdefault(hit.path, []).append(term)
                titles[hit.path] = hit.title
        best = sorted(score, key=lambda p: (-score[p], p))[:limit]
        words = list(dict.fromkeys(w for t in terms for w in query_words(t) or t.split()))
        out = []
        for path in best:
            text = self._read_note(path)
            if text is None:
                continue
            sec = best_hit_section(text, words)
            body = text.split("\n")
            part = "\n".join(body[sec.start - 1 : sec.end]) if sec else text
            out.append(
                Hit(
                    path,
                    titles[path],
                    sec.heading if sec else "",
                    part.strip()[:SNIPPET_CHARS],
                    tuple(matched[path]),
                    round(score[path], 3),
                )
            )
        return out

    # ---- one note ------------------------------------------------------------------------------

    def outline(self, name: str) -> list[HeadingRow]:
        row = self.note(name)
        self._text(row)  # access re-checked on the text
        return self.index.headings_of(row.path)

    def read(self, name: str, section: str = "", max_chars: int = READ_CHARS) -> ReadResult:
        """A note's text, or one section of it, cut at ``max_chars``."""
        row = self.note(name)
        text = self._text(row)
        lines = text.split("\n")
        heading, start, end = "", 1, len(lines)
        if section.strip():
            sec = find_section(text, section)
            if sec is None:
                raise ToolError(f"No section {section!r} in {row.path}.")
            heading, start, end = sec.heading, sec.start, sec.end
        part = "\n".join(lines[start - 1 : end])
        cut = len(part) > max_chars
        return ReadResult(row.path, row.title, heading, start, end, part[:max_chars], cut)
