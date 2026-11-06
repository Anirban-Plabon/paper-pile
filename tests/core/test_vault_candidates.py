"""Vault agent: candidate notes from several sources (PLAN_vault_agent P30.16)."""

from datetime import date
from pathlib import Path

import pytest

from paper_pile.core.ai.access import says_private
from paper_pile.core.ai.vault.candidates import Gatherer
from paper_pile.core.ai.vault.scope import ScopeResolver
from paper_pile.core.ai.vault.tools import VaultTools
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault


@pytest.fixture
def tools(tmp_path: Path) -> VaultTools:
    v = Vault(tmp_path)
    v.create_note("Research/Yunus.md", "# Yunus\nMicrofinance and social business.\n[[Grameen]]\n")
    v.create_note("Research/Grameen.md", "# Grameen\nA bank for the poor.\n")  # no search words
    v.create_note("Research/Enterprise.md", "#social-enterprise\nA company with a mission.\n")
    v.create_note("Personal/Life.md", "My social life is busy.\n")
    v.create_note("Personal/Secret.md", "---\nai: false\n---\nmicrofinance secret\n")
    v.create_note("Ideas/Shop.md", "A microfinance shop idea. See [[Yunus]].\n")
    for i in range(5):
        v.create_note(f"Bulk/n{i}.md", f"microfinance note {i}\n")
    ix = Index(v)
    ix.sync()
    resolver = ScopeResolver(ix, lambda rel: True)

    def read(rel: str) -> str | None:
        text = v.read_text(rel)
        return None if says_private(text) else text

    return VaultTools(ix, resolver, read, today=lambda: date(2026, 11, 6))


def test_sources_combine(tools: VaultTools) -> None:
    found = Gatherer(tools).gather(["microfinance", "social-enterprise"])
    by_path = {c.path: c for c in found.items}
    assert "Personal/Secret.md" not in by_path  # private never a candidate
    assert "search" in by_path["Research/Yunus.md"].sources
    assert "tag" in by_path["Research/Enterprise.md"].sources
    assert found.items[0].score >= found.items[-1].score
    assert not found.capped


def test_link_neighbours_of_strong_hits(tools: VaultTools) -> None:
    found = Gatherer(tools).gather(["social business"])  # only Yunus has both words
    by_path = {c.path: c for c in found.items}
    assert by_path["Research/Yunus.md"].sources == {"search"}
    grameen = by_path["Research/Grameen.md"]  # Yunus links to it; no search word in it
    assert grameen.sources == {"link"} and "bank" in grameen.snippet
    assert by_path["Ideas/Shop.md"].sources == {"link"}  # links to Yunus
    assert "Personal/Life.md" not in by_path  # "social" alone is not "social business"


def test_scope_and_cap(tools: VaultTools) -> None:
    g = Gatherer(tools)
    inside = g.gather(["microfinance"], paths=["Bulk/n0.md", "Bulk/n1.md", "Personal/Secret.md"])
    assert {c.path for c in inside.items} == {"Bulk/n0.md", "Bulk/n1.md"}
    capped = g.gather(["microfinance"], limit=3)
    assert len(capped.items) == 3 and capped.total > 3 and capped.capped


def test_card_source(tools: VaultTools) -> None:
    def cards(terms: object, allowed: set[str]) -> list[tuple[str, float]]:
        return [("Personal/Life.md", 1.0), ("Personal/Secret.md", 1.0)]

    found = Gatherer(tools, cards).gather(["social business"])
    paths = {c.path: c for c in found.items}
    assert "card" in paths["Personal/Life.md"].sources
    assert "Personal/Secret.md" not in paths  # a card source cannot add a private note


def test_from_paths(tools: VaultTools) -> None:
    got = Gatherer(tools).from_paths(["Ideas/Shop.md", "Personal/Secret.md", "Ideas/Shop.md"])
    assert [c.path for c in got.items] == ["Ideas/Shop.md"] and got.total == 1
    assert got.items[0].sources == {"scope"} and "microfinance" in got.items[0].snippet
