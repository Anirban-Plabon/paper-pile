"""Searching a list of notes for the note picker (link to note, embed note, templates) and the
quick switcher (Ctrl+O)."""

from collections.abc import Iterable

from paper_pile.core.commands import match_score


def search_notes(query: str, paths: Iterable[str], limit: int = 50) -> list[str]:
    """Note paths matching ``query``, best first. The file name counts more than the folder, so
    ``idea`` finds ``Idea.md`` before ``ideas/other.md``. No query: everything, alphabetically."""
    ordered = sorted(paths, key=str.lower)
    if not query.strip():
        return ordered[:limit]
    scored: list[tuple[int, int, str]] = []
    for i, path in enumerate(ordered):
        name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        by_name = match_score(query, name)
        by_path = match_score(query, path)
        best = max(
            (s for s in (by_name, None if by_path is None else by_path - 15) if s is not None),
            default=None,
        )
        if best is not None:
            scored.append((-best, i, path))
    scored.sort()
    return [path for _score, _i, path in scored[:limit]]


def switcher_notes(
    query: str, paths: Iterable[str], recent: Iterable[str], limit: int = 50
) -> list[str]:
    """What the quick switcher lists: with no query, the recently opened notes that still exist
    (newest first) and then the rest alphabetically; with a query, :func:`search_notes`."""
    every = list(paths)
    if query.strip():
        return search_notes(query, every, limit)
    known = set(every)
    first = [p for p in dict.fromkeys(recent) if p in known]
    rest = [p for p in sorted(every, key=str.lower) if p not in set(first)]
    return (first + rest)[:limit]
