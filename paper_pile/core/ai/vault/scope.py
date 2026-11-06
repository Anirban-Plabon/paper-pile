"""Which notes a vault request is about (PLAN_vault_agent §3.1, P30.9): folders, tags, dates,
named notes and links, combined — each kind narrows the set, values of one kind widen it
("#a or #b, in Clients, from October"). Private notes (``ai: false``, excluded by the access
grant) are never in a result, never named as a candidate, never counted.
"""

import difflib
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from paper_pile.core.ai.vault.dates import DayRange, date_range
from paper_pile.core.daily import DEFAULT_FORMAT, daily_date
from paper_pile.core.index import Index, NoteRow
from paper_pile.core.links import norm_name, parse_wikilink, resolve_md_link, resolve_wikilink
from paper_pile.core.tags import norm_tag

log = logging.getLogger("paper_pile.ai.vault.scope")

DateKind = Literal["content", "edited", "any"]
NAME_CUTOFF = 0.75  # how close a misspelt note / folder name must be to count


@dataclass(frozen=True, slots=True)
class Scope:
    """What the request narrows to; empty fields do not narrow."""

    folders: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()  # note names as the user wrote them
    linked_from: tuple[str, ...] = ()  # notes whose links to follow
    links_to: tuple[str, ...] = ()  # notes whose backlinks to take
    dates: DayRange | None = None
    date_kind: DateKind = "content"  # content: daily / front-matter dates; edited: mtime

    @property
    def empty(self) -> bool:
        return not (
            self.folders or self.tags or self.notes or self.linked_from or self.links_to
        ) and (self.dates is None)


def _strings(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return ()
    return tuple(dict.fromkeys(s.strip() for s in raw if isinstance(s, str) and s.strip()))


def scope_from_json(data: object, today: date) -> Scope:
    """A :class:`Scope` from the understanding step's ``target`` object; anything malformed is
    left out (a scope that narrows less, never an error)."""
    if not isinstance(data, Mapping):
        return Scope()
    kind = data.get("date_kind")
    return Scope(
        folders=tuple(f.strip("/") for f in _strings(data.get("folders"))),
        tags=tuple(t.lstrip("#") for t in _strings(data.get("tags"))),
        notes=_strings(data.get("notes")),
        linked_from=_strings(data.get("linked_from")),
        links_to=_strings(data.get("links_to")),
        dates=date_range(data.get("dates"), today),
        date_kind=kind if kind in ("content", "edited", "any") else "content",
    )


@dataclass(slots=True)
class Resolved:
    """A resolved scope: the notes, and what did not resolve cleanly (for the agent to ask)."""

    paths: list[str]
    ambiguous: dict[str, list[str]] = field(default_factory=dict)  # name → its candidates
    missing: list[str] = field(default_factory=list)  # names / folders / tags with no match


def _stem(path: str) -> str:
    return norm_name(path.rsplit("/", 1)[-1])


def match_names(name: str, rows: Iterable[NoteRow]) -> list[str]:
    """The notes ``name`` most likely means, best tier only: the exact path (for a name with a
    folder), then the file name or title, then names containing it, then close spellings.
    [] when nothing is close; several when the name fits several notes equally."""
    rows = list(rows)
    whole = [r.path for r in rows if r.path == name.strip()]  # a full path, extension included
    if whole:
        return whole
    key = norm_name(name.strip().strip("[]").split("|", 1)[0].split("#", 1)[0])
    if not key:
        return []
    tiers: list[Callable[[NoteRow], bool]] = [
        lambda r: "/" in key and norm_name(r.path) == key,  # only a name written with a folder
        lambda r: _stem(r.path) == key or r.title.casefold() == key,
        lambda r: key in _stem(r.path) or key in r.title.casefold(),
    ]
    for tier in tiers:
        found = [r.path for r in rows if tier(r)]
        if found:
            return found
    names: dict[str, list[str]] = {}
    for r in rows:
        names.setdefault(_stem(r.path), []).append(r.path)
        names.setdefault(r.title.casefold(), []).append(r.path)
    close = difflib.get_close_matches(key, list(names), n=3, cutoff=NAME_CUTOFF)
    return list(dict.fromkeys(p for c in close for p in names[c]))


def match_folders(name: str, folders: Iterable[str]) -> list[str]:
    """Vault folders ``name`` means: the exact path, else folders whose last part is the name
    (``Clients`` finds ``Work/Clients``), else close spellings. A name written with a ``/``
    is only compared with whole paths of the same depth, so a missing ``Clients/x`` never
    turns into ``Clients``."""
    key = name.strip().strip("/").casefold()
    if not key:
        return []
    folders = list(folders)
    exact = [f for f in folders if f.casefold() == key]
    if exact:
        return exact
    if "/" in key:
        depth = key.count("/")
        same = {f.casefold(): f for f in folders if f.count("/") == depth}
        close = difflib.get_close_matches(key, list(same), n=3, cutoff=NAME_CUTOFF)
        return [same[c] for c in close]
    tail = [f for f in folders if f.rsplit("/", 1)[-1].casefold() == key]
    if tail:
        return tail
    tails: dict[str, list[str]] = {}
    for f in folders:
        tails.setdefault(f.rsplit("/", 1)[-1].casefold(), []).append(f)
    close = difflib.get_close_matches(key, list(tails), n=3, cutoff=NAME_CUTOFF)
    return [f for c in close for f in tails[c]]


def note_folders(paths: Iterable[str]) -> list[str]:
    """Every folder that holds notes, at any depth (``a``, ``a/b``)."""
    out: dict[str, None] = {}
    for path in paths:
        parts = path.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            out.setdefault("/".join(parts[:i]), None)
    return sorted(out)


class ScopeResolver:
    """Resolves a :class:`Scope` against the index. ``may_read`` is the access check
    (``AccessPolicy.may_read``); the index's ``private`` flag covers ``ai: false``."""

    def __init__(
        self,
        index: Index,
        may_read: Callable[[str], bool],
        *,
        daily_folder: str = "",
        daily_format: str = DEFAULT_FORMAT,
    ) -> None:
        self.index = index
        self.may_read = may_read
        self.daily_folder = daily_folder
        self.daily_format = daily_format

    def readable(self) -> list[NoteRow]:
        """Every note the AI may read, by path."""
        return [r for r in self.index.note_rows() if not r.private and self.may_read(r.path)]

    def content_days(self, rows: Iterable[NoteRow], days: DayRange) -> set[str]:
        """Notes dated inside ``days``: a daily note's own date, or a front-matter date."""
        start, end = days.iso()
        found = {d.path for d in self.index.dated_notes(start, end)}
        if self.daily_folder:
            for r in rows:
                day = daily_date(r.path, self.daily_folder, self.daily_format)
                if day is not None and days.holds(day):
                    found.add(r.path)
        return found

    def _dated(self, rows: list[NoteRow], scope: Scope) -> set[str]:
        assert scope.dates is not None
        edited = {r.path for r in rows if scope.dates.holds(datetime.fromtimestamp(r.mtime).date())}
        if scope.date_kind == "edited":
            return edited
        content = self.content_days(rows, scope.dates)
        return content | edited if scope.date_kind == "any" else content

    def _names(self, names: Iterable[str], rows: list[NoteRow], out: Resolved) -> set[str]:
        found: set[str] = set()
        for name in names:
            hits = match_names(name, rows)
            if not hits:
                out.missing.append(name)
            elif len(hits) > 1:
                out.ambiguous[name] = hits
            found.update(hits)
        return found

    def _links_out(self, sources: set[str], paths: set[str]) -> set[str]:
        found: set[str] = set()
        for src in sources:
            for link in self.index.links_from(src):
                if link.kind == "wiki":
                    parsed = parse_wikilink(link.dst_raw)
                    dst = resolve_wikilink(parsed.note, src, paths) if parsed else None
                else:
                    dst = resolve_md_link(link.dst_raw, src, paths)
                if dst and dst != src:
                    found.add(dst)
        return found

    def resolve(self, scope: Scope) -> Resolved:
        rows = self.readable()
        out = Resolved(paths=[])
        keep = {r.path for r in rows}
        if scope.folders:
            folders = note_folders(keep)
            prefixes: list[str] = []
            for name in scope.folders:
                hits = match_folders(name, folders)
                if not hits:
                    out.missing.append(name)
                elif len(hits) > 1:
                    out.ambiguous[name] = hits
                prefixes += [h + "/" for h in hits]
            keep = {p for p in keep if p.startswith(tuple(prefixes))} if prefixes else set()
        if scope.tags:
            tagged: set[str] = set()
            for tag in scope.tags:
                tag_hits = {n.path for n in self.index.notes_with_tag(tag)}
                if not tag_hits:
                    out.missing.append("#" + norm_tag(tag))
                tagged |= tag_hits
            keep &= tagged
        if scope.dates is not None:
            keep &= self._dated(rows, scope)
        if scope.notes:
            keep &= self._names(scope.notes, rows, out)
        readable = {r.path for r in rows}
        if scope.linked_from:
            keep &= self._links_out(self._names(scope.linked_from, rows, out), readable)
        if scope.links_to:
            targets = self._names(scope.links_to, rows, out)
            sources = {b.src for t in targets for b in self.index.backlinks(t)}
            keep &= sources & readable
        out.paths = sorted(keep)
        return out


def describe(scope: Scope) -> dict[str, Any]:
    """The scope as plain data (the step card, logs, the eval)."""
    out: dict[str, Any] = {}
    for name in ("folders", "tags", "notes", "linked_from", "links_to"):
        value = getattr(scope, name)
        if value:
            out[name] = list(value)
    if scope.dates is not None:
        out["dates"] = list(scope.dates.iso())
        out["date_kind"] = scope.date_kind
    return out
