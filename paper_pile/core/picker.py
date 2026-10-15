"""Searching a list of notes for the note picker (link to note, embed note, templates)."""

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
