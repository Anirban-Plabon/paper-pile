"""Vault agent: read tools, meta queries, result set (PLAN_vault_agent P30.10–P30.12).

Every tool is checked against private notes: an ``ai: false`` note and a folder the grant
excludes must never be listed, searched, read, counted or offered as a candidate.
"""

import os
import time
from datetime import date
from pathlib import Path

import pytest

from paper_pile.core.ai.access import says_private
from paper_pile.core.ai.vault.dates import DayRange
from paper_pile.core.ai.vault.meta import QUERIES, VaultMeta
from paper_pile.core.ai.vault.results import ResultItem, ResultSet
from paper_pile.core.ai.vault.scope import Scope, ScopeResolver
from paper_pile.core.ai.vault.tools import (
    AmbiguousNoteError,
    NoSuchNoteError,
    ToolError,
    VaultTools,
    find_section,
    sections,
)
from paper_pile.core.index import Index
from paper_pile.core.vault import Vault

PRIVATE = ("Clients/Secret.md", "Private/Diary.md")

ACME = """# Acme

Intro line.

## Budget

Budget is 10k for social business work.

### Detail

Line items.

## Contacts

Jane. See [[Pricing]].
"""


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.create_note("Clients/Acme.md", ACME)
    v.create_note("Clients/Beta.md", "---\ndate: 2026-10-14\n---\n#client Microfinance pilot.\n")
    v.create_note("Clients/Secret.md", "---\nai: false\n---\nsocial business secret budget\n")
    v.create_note("Pricing.md", "# Pricing\nSocial business pricing tiers.\n")
    v.create_note("Ideas/Pricing.md", "# Pricing ideas\nfree tier\n")
    v.create_note("Ideas/Cafe.md", "#idea a social cafe\n")
    v.create_note("Journal/2026-10-20.md", "daily stuff about business\n")
    v.create_note("Private/Diary.md", "social business diary\n")
    old = time.mktime((2025, 6, 1, 12, 0, 0, 0, 0, -1))
    os.utime(v.resolve("Ideas/Cafe.md"), (old, old))
    return v


def _may_read(rel: str) -> bool:
    return not rel.startswith("Private/")


@pytest.fixture
def tools(vault: Vault) -> VaultTools:
    ix = Index(vault)
    ix.sync()
    resolver = ScopeResolver(ix, _may_read, daily_folder="Journal")

    def read_note(rel: str) -> str | None:
        if not _may_read(rel):
            return None
        text = vault.read_text(rel)
        return None if says_private(text) else text

    return VaultTools(ix, resolver, read_note, today=lambda: date(2026, 11, 6))


@pytest.fixture
def meta(tools: VaultTools) -> VaultMeta:
    return VaultMeta(tools.index, tools.resolver)


def no_private(paths: list[str]) -> None:
    assert not set(paths) & set(PRIVATE)


# ---- sections --------------------------------------------------------------------------------


def test_sections() -> None:
    got = [(s.heading, s.level, s.start, s.end) for s in sections(ACME)]
    assert got == [
        ("Acme", 1, 1, 16),
        ("Budget", 2, 5, 12),
        ("Detail", 3, 9, 12),
        ("Contacts", 2, 13, 16),
    ]
    assert [(s.heading, s.start, s.end) for s in sections("intro\n# H\nx")] == [
        ("", 1, 1),
        ("H", 2, 3),
    ]
    sec = find_section(ACME, " budget ")
    assert sec is not None and (sec.start, sec.end) == (5, 12)
    assert find_section(ACME, "nope") is None


# ---- listings --------------------------------------------------------------------------------


def test_list_folder(tools: VaultTools) -> None:
    every = [n.path for n in tools.list_folder()]
    no_private(every)
    assert len(every) == 6
    assert [n.path for n in tools.list_folder("clients")] == ["Clients/Acme.md", "Clients/Beta.md"]
    assert [n.path for n in tools.list_folder("", recursive=False)] == ["Pricing.md"]
    with pytest.raises(ToolError):
        tools.list_folder("Private")
    with pytest.raises(ToolError):
        tools.list_folder("Nowhere")


def test_by_date_and_tag(tools: VaultTools) -> None:
    october = DayRange(date(2026, 10, 1), date(2026, 10, 31))
    assert [n.path for n in tools.by_date(october)] == ["Clients/Beta.md", "Journal/2026-10-20.md"]
    year_2025 = DayRange(date(2025, 1, 1), date(2025, 12, 31))
    assert [n.path for n in tools.by_date(year_2025, "edited")] == ["Ideas/Cafe.md"]
    assert [n.path for n in tools.by_tag("client")] == ["Clients/Beta.md"]


def test_links(tools: VaultTools) -> None:
    assert [n.path for n in tools.links("Acme", "out")] == ["Pricing.md"]
    assert [n.path for n in tools.links("Pricing.md", "in")] == ["Clients/Acme.md"]


# ---- names -----------------------------------------------------------------------------------


def test_note_names(tools: VaultTools) -> None:
    assert tools.note("acme").path == "Clients/Acme.md"
    with pytest.raises(AmbiguousNoteError) as amb:
        tools.note("pricing")
    assert amb.value.candidates == ["Ideas/Pricing.md", "Pricing.md"]
    with pytest.raises(NoSuchNoteError):
        tools.note("Secret")  # private: as if it did not exist
    with pytest.raises(NoSuchNoteError):
        tools.note("Diary")


# ---- search ----------------------------------------------------------------------------------


def test_search_ranks_and_hides_private(tools: VaultTools) -> None:
    hits = tools.search(["social business", "microfinance"])
    paths = [h.path for h in hits]
    no_private(paths)
    assert set(paths) == {"Clients/Acme.md", "Pricing.md", "Clients/Beta.md"}
    acme = next(h for h in hits if h.path == "Clients/Acme.md")
    assert acme.heading == "Budget" and "10k" in acme.snippet
    assert acme.terms == ("social business",)


def test_search_more_terms_rank_higher(tools: VaultTools) -> None:
    hits = tools.search(["pricing", "social business"])
    assert hits[0].path == "Pricing.md"  # matches both terms


def test_search_in_scope(tools: VaultTools) -> None:
    hits = tools.search(["social"], Scope(folders=("Ideas",)))
    assert [h.path for h in hits] == ["Ideas/Cafe.md"]
    assert tools.search(["   "]) == []


# ---- reading ---------------------------------------------------------------------------------


def test_read_whole_and_section(tools: VaultTools) -> None:
    whole = tools.read("acme")
    assert whole.start == 1 and whole.end == 16 and not whole.cut and "Jane" in whole.text
    part = tools.read("acme", "Budget")
    assert (part.heading, part.start, part.end) == ("Budget", 5, 12)
    assert "Line items" in part.text and "Jane" not in part.text
    cut = tools.read("acme", max_chars=10)
    assert cut.cut and len(cut.text) == 10
    with pytest.raises(ToolError):
        tools.read("acme", "Missing")


def test_read_refuses_private(tools: VaultTools, vault: Vault) -> None:
    with pytest.raises(NoSuchNoteError):
        tools.read("Clients/Secret.md")
    # turned private after indexing: the text check still refuses it
    vault.write_text("Pricing.md", "---\nai: false\n---\nnow private\n")
    with pytest.raises(NoSuchNoteError):
        tools.read("Pricing.md")
    with pytest.raises(NoSuchNoteError):
        tools.outline("Pricing.md")


def test_outline(tools: VaultTools) -> None:
    assert [h.text for h in tools.outline("acme")] == ["Acme", "Budget", "Detail", "Contacts"]


# ---- meta ------------------------------------------------------------------------------------


def test_meta_count_and_folders(meta: VaultMeta) -> None:
    count = meta.run("count")
    assert count.rows[0][0] == 6  # private notes not counted
    assert meta.run("count", Scope(folders=("Clients",))).rows[0][0] == 2
    folders = dict(meta.run("folders").rows)
    assert folders == {"Clients": 2, "Ideas": 2, "Journal": 1, "(top)": 1}


def test_meta_lists(meta: VaultMeta) -> None:
    recent = meta.run("recent", limit=2)
    assert recent.total == 6 and len(recent.rows) == 2
    assert "Ideas/Cafe.md" not in [r[0] for r in recent.rows]  # the oldest one
    year_2025 = DayRange(date(2025, 1, 1), date(2025, 12, 31))
    assert [r[0] for r in meta.run("recent", days=year_2025).rows] == ["Ideas/Cafe.md"]
    lonely = [r[0] for r in meta.run("no_links").rows]
    assert "Clients/Acme.md" not in lonely and "Pricing.md" not in lonely
    assert "Ideas/Cafe.md" in lonely
    no_private(lonely)
    largest = meta.run("largest", limit=1)
    assert largest.rows[0][0] == "Clients/Acme.md" and largest.columns[-1] == "words"
    untagged = [r[0] for r in meta.run("untagged").rows]
    assert "Clients/Beta.md" not in untagged and "Ideas/Cafe.md" not in untagged
    no_private(untagged)


def test_meta_tags_skip_private(meta: VaultMeta, vault: Vault, tools: VaultTools) -> None:
    vault.write_text("Private/Diary.md", "#client #secret-tag\n")
    tools.index.update_note("Private/Diary.md")
    assert dict(meta.run("tags").rows) == {"#client": 1, "#idea": 1}


def test_meta_rejects_unknown(meta: VaultMeta) -> None:
    assert "count" in QUERIES
    with pytest.raises(ValueError):
        meta.run("drop table")


# ---- result set ------------------------------------------------------------------------------


def test_result_set() -> None:
    rs = ResultSet(
        "social business notes",
        [
            ResultItem("a.md", "A", "budget for it"),
            ResultItem("b.md", "B", relevance="maybe"),
            ResultItem("c.md", "C"),
        ],
    )
    assert [i.path for i in rs.pick("all")] == ["a.md", "b.md", "c.md"]
    assert [i.path for i in rs.pick([2, "3", 9, True])] == ["b.md", "c.md"]
    assert [i.path for i in rs.pick("maybe")] == ["b.md"]
    assert [i.path for i in rs.pick(["c.md", "zz.md"])] == ["c.md"]
    assert rs.renamed("a.md", "x/a.md").paths == ["x/a.md", "b.md", "c.md"]
    assert rs.without_paths(["b.md"]).paths == ["a.md", "c.md"]
    text = rs.compact()
    assert "1. A [a.md] — budget for it" in text and "2. B [b.md] (maybe)" in text
    assert ResultSet.from_json(rs.to_json()) == rs
    assert ResultSet.from_json({"items": [{"title": "no path"}, 3]}).items == []
    assert len(ResultSet.from_json(None)) == 0
