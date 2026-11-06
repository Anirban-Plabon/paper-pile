"""Candidate notes for a step (PLAN_vault_agent §4 step 2, P30.16): gathered from several
sources and ranked — full-text search on the step's widened terms, tags that a term names,
note cards (P30.18) when given, and the link neighbours of the strongest hits — always inside
the step's scope and never a private note. The judge (``judge.py``) decides which are really
about the topic. No model calls here.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from paper_pile.core.ai.vault.tools import SNIPPET_CHARS, ToolError, VaultTools
from paper_pile.core.tags import norm_tag

MAX_CANDIDATES = 60
NEIGHBOUR_SEEDS = 5  # the strongest hits whose links are followed (one hop)
TAG_SCORE = 2.0  # a note carrying a tag a term names
CARD_SCORE = 1.5  # per card hit (its summary matched a term)
NEIGHBOUR_SCORE = 0.5  # linked from / to a strong hit


@dataclass(slots=True)
class Candidate:
    path: str
    title: str
    score: float = 0.0
    sources: set[str] = field(default_factory=set)  # search, tag, card, link, scope
    heading: str = ""
    snippet: str = ""
    terms: tuple[str, ...] = ()
    summary: str = ""  # the note card's summary, when one is current (P30.18)


@dataclass(slots=True)
class Candidates:
    items: list[Candidate]  # best first, at most the cap
    total: int  # how many were found before the cap

    @property
    def capped(self) -> bool:
        return self.total > len(self.items)


# a card search: (terms, allowed paths) -> [(path, score)]; P30.18
CardSearch = Callable[[Sequence[str], set[str]], list[tuple[str, float]]]
# current card summaries of some notes: paths -> {path: summary}
Summaries = Callable[[Sequence[str]], dict[str, str]]


class Gatherer:
    def __init__(
        self,
        tools: VaultTools,
        cards: CardSearch | None = None,
        summaries: Summaries | None = None,
    ) -> None:
        self.tools = tools
        self.cards = cards
        self.summaries = summaries

    def _summarise(self, items: list[Candidate]) -> None:
        if self.summaries is None or not items:
            return
        known = self.summaries([c.path for c in items])
        for c in items:
            c.summary = known.get(c.path, "")

    def _allowed(self, paths: Sequence[str] | None) -> set[str]:
        readable = {r.path for r in self.tools.resolver.readable()}
        return readable if paths is None else readable & set(paths)

    def _snippet(self, path: str) -> str:
        try:
            return self.tools.read(path, max_chars=SNIPPET_CHARS).text.strip()
        except ToolError:
            return ""

    def from_paths(self, paths: Sequence[str], limit: int = MAX_CANDIDATES) -> Candidates:
        """A step with a fixed note set (a folder, named notes, the last result): every note is
        a candidate, in the given order."""
        allowed = self._allowed(paths)
        titles = {r.path: r.title for r in self.tools.resolver.readable()}
        keep = [p for p in dict.fromkeys(paths) if p in allowed]
        items = [
            Candidate(p, titles[p], 1.0, {"scope"}, snippet=self._snippet(p)) for p in keep[:limit]
        ]
        self._summarise(items)
        return Candidates(items, len(keep))

    def gather(
        self,
        terms: Sequence[str],
        paths: Sequence[str] | None = None,
        limit: int = MAX_CANDIDATES,
    ) -> Candidates:
        """Candidates for ``terms`` inside ``paths`` (None: the whole readable vault)."""
        allowed = self._allowed(paths)
        found: dict[str, Candidate] = {}
        titles = {r.path: r.title for r in self.tools.resolver.readable()}

        def add(path: str, score: float, source: str) -> Candidate | None:
            if path not in allowed:
                return None
            cand = found.setdefault(path, Candidate(path, titles.get(path, path)))
            cand.score += score
            cand.sources.add(source)
            return cand

        within = allowed if paths is not None else None
        for hit in self.tools.search(terms, None, limit=limit * 2, within=within):
            cand = add(hit.path, hit.score, "search")
            if cand is not None:
                cand.heading, cand.snippet, cand.terms = hit.heading, hit.snippet, hit.terms

        tags = {norm_tag(t.lstrip("#")) for t in terms}
        for path, tag in self.tools.index.tag_pairs():
            if tag in tags or any(tag.startswith(t + "/") for t in tags if t):
                add(path, TAG_SCORE, "tag")

        if self.cards is not None:
            for path, score in self.cards(terms, allowed):
                add(path, CARD_SCORE * score, "card")

        seeds = sorted(found.values(), key=lambda c: -c.score)[:NEIGHBOUR_SEEDS]
        for seed in seeds:
            for direction in ("out", "in"):
                try:
                    neighbours = self.tools.links(seed.path, direction)
                except ToolError:
                    continue
                for n in neighbours:
                    add(n.path, NEIGHBOUR_SCORE, "link")

        ranked = sorted(found.values(), key=lambda c: (-c.score, c.path))
        for cand in ranked[:limit]:
            if not cand.snippet:
                cand.snippet = self._snippet(cand.path)
        self._summarise(ranked[:limit])
        return Candidates(ranked[:limit], len(ranked))
