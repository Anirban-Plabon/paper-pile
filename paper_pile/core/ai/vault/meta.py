"""Facts about the vault answered from the index with no model call (PLAN_vault_agent §3.2
``meta``, P30.11): counts, recent changes, notes nothing links to, the largest notes, notes
without tags, tags in use. Only notes the AI may read are looked at or counted.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from paper_pile.core.ai.vault.dates import DayRange
from paper_pile.core.ai.vault.scope import Scope, ScopeResolver
from paper_pile.core.index import Index, NoteRow
from paper_pile.core.links import link_keys

QUERIES = ("count", "folders", "recent", "no_links", "largest", "untagged", "tags")
DEFAULT_LIMIT = 20


@dataclass(slots=True)
class MetaResult:
    query: str
    total: int  # how many there are in all (rows may be cut at the limit)
    columns: list[str]
    rows: list[list[Any]] = field(default_factory=list)


def _edited(row: NoteRow) -> str:
    return datetime.fromtimestamp(row.mtime).date().isoformat()


class VaultMeta:
    def __init__(self, index: Index, resolver: ScopeResolver) -> None:
        self.index = index
        self.resolver = resolver

    def _rows(self, scope: Scope | None) -> list[NoteRow]:
        rows = self.resolver.readable()
        if scope is None or scope.empty:
            return rows
        keep = set(self.resolver.resolve(scope).paths)
        return [r for r in rows if r.path in keep]

    def run(
        self,
        query: str,
        scope: Scope | None = None,
        *,
        days: DayRange | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> MetaResult:
        """One of :data:`QUERIES` over the readable notes in ``scope``. ``days`` limits
        ``recent`` to changes in that range (else the latest changes)."""
        if query not in QUERIES:
            raise ValueError(f"unknown meta query {query!r}")
        rows = self._rows(scope)
        run: Callable[[list[NoteRow], DayRange | None, int], MetaResult] = getattr(
            self, f"_q_{query}"
        )
        return run(rows, days, max(1, limit))

    def _list(self, query: str, rows: list[NoteRow], limit: int, extra: str = "") -> MetaResult:
        cols = ["path", "title", "edited"] + ([extra] if extra else [])
        out = MetaResult(query, len(rows), cols)
        for r in rows[:limit]:
            line: list[Any] = [r.path, r.title, _edited(r)]
            if extra == "words":
                line.append(r.words)
            out.rows.append(line)
        return out

    def _q_count(self, rows: list[NoteRow], _days: DayRange | None, _limit: int) -> MetaResult:
        return MetaResult(
            "count", len(rows), ["notes", "words"], [[len(rows), sum(r.words for r in rows)]]
        )

    def _q_folders(self, rows: list[NoteRow], _days: DayRange | None, limit: int) -> MetaResult:
        counts = Counter(r.path.split("/", 1)[0] if "/" in r.path else "" for r in rows)
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return MetaResult(
            "folders",
            len(ordered),
            ["folder", "notes"],
            [[f or "(top)", n] for f, n in ordered[:limit]],
        )

    def _q_recent(self, rows: list[NoteRow], days: DayRange | None, limit: int) -> MetaResult:
        if days is not None:
            rows = [r for r in rows if days.holds(datetime.fromtimestamp(r.mtime).date())]
        rows = sorted(rows, key=lambda r: (-r.mtime, r.path))
        return self._list("recent", rows, limit)

    def _q_no_links(self, rows: list[NoteRow], _days: DayRange | None, limit: int) -> MetaResult:
        """Notes with no links out and no link to them (by name: cheap, no resolving)."""
        out_counts, keys = self.index.link_stats()
        lonely = [
            r
            for r in rows
            if not out_counts.get(r.path) and not any(k in keys for k in link_keys([r.path]))
        ]
        return self._list("no_links", lonely, limit)

    def _q_largest(self, rows: list[NoteRow], _days: DayRange | None, limit: int) -> MetaResult:
        rows = sorted(rows, key=lambda r: (-r.words, r.path))
        return self._list("largest", rows, limit, extra="words")

    def _q_untagged(self, rows: list[NoteRow], _days: DayRange | None, limit: int) -> MetaResult:
        tagged = self.index.tagged_paths()
        return self._list("untagged", [r for r in rows if r.path not in tagged], limit)

    def _q_tags(self, rows: list[NoteRow], _days: DayRange | None, limit: int) -> MetaResult:
        keep = {r.path for r in rows}
        counts = Counter(tag for path, tag in self.index.tag_pairs() if path in keep)
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return MetaResult(
            "tags", len(ordered), ["tag", "notes"], [[f"#{t}", n] for t, n in ordered[:limit]]
        )
