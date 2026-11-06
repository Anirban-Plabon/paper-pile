"""Vault agent: date ranges and the scope resolver (PLAN_vault_agent P30.9)."""

import os
import time
from datetime import date
from pathlib import Path

import pytest

from paper_pile.core.ai.vault.dates import DayRange, date_range
from paper_pile.core.ai.vault.scope import (
    Scope,
    ScopeResolver,
    describe,
    match_folders,
    match_names,
    scope_from_json,
)
from paper_pile.core.index import Index, NoteRow
from paper_pile.core.vault import Vault

TODAY = date(2026, 11, 6)  # a Friday


def d(s: str) -> date:
    return date.fromisoformat(s)


# ---- dates -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "start", "end"),
    [
        ({"this": "day"}, "2026-11-06", "2026-11-06"),
        ({"last": "day"}, "2026-11-05", "2026-11-05"),
        ({"this": "week"}, "2026-11-02", "2026-11-08"),
        ({"last": "week"}, "2026-10-26", "2026-11-01"),
        ({"this": "month"}, "2026-11-01", "2026-11-30"),
        ({"last": "month"}, "2026-10-01", "2026-10-31"),
        ({"last": "year"}, "2025-01-01", "2025-12-31"),
        ({"past": 7, "unit": "day"}, "2026-10-31", "2026-11-06"),
        ({"past": 2, "unit": "month"}, "2026-09-07", "2026-11-06"),
        ({"year": 2025}, "2025-01-01", "2025-12-31"),
        ({"year": 2025, "month": 2}, "2025-02-01", "2025-02-28"),
        ({"month": 10}, "2026-10-01", "2026-10-31"),  # latest October that has started
        ({"month": 12}, "2025-12-01", "2025-12-31"),  # December 2026 has not started yet
        ({"month": "3", "day": 9}, "2026-03-09", "2026-03-09"),
        ({"from": "2026-01-01", "to": "2026-01-15"}, "2026-01-01", "2026-01-15"),
        ({"from": "2026-11-01"}, "2026-11-01", "2026-11-06"),
    ],
)
def test_date_range(spec: dict[str, object], start: str, end: str) -> None:
    assert date_range(spec, TODAY) == DayRange(d(start), d(end))


@pytest.mark.parametrize(
    "spec",
    [
        None,
        "last week",
        {},
        {"this": "fortnight"},
        {"month": 13},
        {"day": 3},
        {"year": 2025, "month": 2, "day": 30},
        {"from": "2026-02-01", "to": "2026-01-01"},
        {"from": "soon"},
        {"past": 0, "unit": "day"},
        {"past": True, "unit": "day"},
    ],
)
def test_date_range_rejects(spec: object) -> None:
    assert date_range(spec, TODAY) is None


def test_month_clamps_on_shift() -> None:
    assert date_range({"past": 1, "unit": "month"}, date(2026, 3, 31)) == DayRange(
        d("2026-03-01"), d("2026-03-31")
    )


# ---- names and folders -----------------------------------------------------------------------


def row(path: str, title: str = "") -> NoteRow:
    return NoteRow(path, title or path.rsplit("/", 1)[-1][:-3], 0.0, 0, False)


ROWS = [
    row("Pricing.md"),
    row("Clients/Pricing.md"),
    row("Clients/Acme.md", "Acme Corp"),
    row("Ideas/Cafe idea.md"),
    row("Journal/2026-11-05.md"),
]


def test_match_names_tiers() -> None:
    assert match_names("Clients/Pricing", ROWS) == ["Clients/Pricing.md"]  # exact path
    assert match_names("pricing", ROWS) == ["Pricing.md", "Clients/Pricing.md"]  # ambiguous
    assert match_names("acme corp", ROWS) == ["Clients/Acme.md"]  # title
    assert match_names("[[Cafe idea|x]]", ROWS) == ["Ideas/Cafe idea.md"]
    assert match_names("cafe", ROWS) == ["Ideas/Cafe idea.md"]  # contains
    assert match_names("Pricng", ROWS) == ["Pricing.md", "Clients/Pricing.md"]  # close spelling
    assert match_names("quantum", ROWS) == []
    assert match_names("  ", ROWS) == []


def test_match_folders() -> None:
    folders = ["Work", "Work/Clients", "Clients", "Archive/Clients", "Marketing"]
    assert match_folders("Work/Clients", folders) == ["Work/Clients"]
    assert match_folders("clients/", folders) == ["Clients"]  # exact beats last-part
    assert match_folders("marketng", folders) == ["Marketing"]
    assert match_folders("nothing", folders) == []
    assert match_folders("clients/x", folders) == []  # a missing subfolder is not its parent
    assert match_folders("work/clinets", folders) == ["Work/Clients"]  # same depth, close
    assert set(match_folders("clients", ["Work/Clients", "Archive/Clients"])) == {
        "Work/Clients",
        "Archive/Clients",
    }


def test_scope_from_json() -> None:
    sc = scope_from_json(
        {
            "folders": ["Clients/"],
            "tags": "#idea",
            "notes": ["Plan", 3, ""],
            "dates": {"last": "week"},
            "date_kind": "bogus",
        },
        TODAY,
    )
    assert sc.folders == ("Clients",) and sc.tags == ("idea",) and sc.notes == ("Plan",)
    assert sc.dates == DayRange(d("2026-10-26"), d("2026-11-01")) and sc.date_kind == "content"
    assert scope_from_json("nope", TODAY).empty
    assert describe(sc)["dates"] == ["2026-10-26", "2026-11-01"]


# ---- resolving against a real index ------------------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.create_note("Clients/Acme.md", "# Acme\n#client budget 10k. See [[Pricing]].\n")
    v.create_note("Clients/Beta.md", "---\ndate: 2026-10-14\n---\n#client #idea Beta notes\n")
    v.create_note("Clients/Secret.md", "---\nai: false\n---\n#client hidden\n")
    v.create_note("Pricing.md", "# Pricing\nprices. Links [[Clients/Beta]].\n")
    v.create_note("Ideas/Cafe.md", "#idea a cafe\n")
    v.create_note("Journal/2026-10-20.md", "daily stuff\n")
    v.create_note("Journal/2026-11-05.md", "yesterday\n")
    v.create_note("Private/Diary.md", "excluded by the grant\n")
    old = time.mktime((2025, 6, 1, 12, 0, 0, 0, 0, -1))
    for p in ("Ideas/Cafe.md", "Pricing.md"):
        os.utime(v.resolve(p), (old, old))
    return v


@pytest.fixture
def resolver(vault: Vault) -> ScopeResolver:
    ix = Index(vault)
    ix.sync()
    return ScopeResolver(
        ix,
        lambda rel: not rel.startswith("Private/"),
        daily_folder="Journal",
        daily_format="YYYY-MM-DD",
    )


def test_private_never_in_results(resolver: ScopeResolver) -> None:
    paths = resolver.resolve(Scope()).paths
    assert "Clients/Secret.md" not in paths and "Private/Diary.md" not in paths
    assert len(paths) == 6
    res = resolver.resolve(Scope(notes=("Secret",), folders=("Private",)))
    assert res.paths == [] and res.missing == ["Private", "Secret"]


def test_folder_and_tag_narrow(resolver: ScopeResolver) -> None:
    assert resolver.resolve(Scope(folders=("clients",))).paths == [
        "Clients/Acme.md",
        "Clients/Beta.md",
    ]
    assert resolver.resolve(Scope(tags=("idea",))).paths == ["Clients/Beta.md", "Ideas/Cafe.md"]
    assert resolver.resolve(Scope(folders=("Clients",), tags=("#idea",))).paths == [
        "Clients/Beta.md"
    ]
    res = resolver.resolve(Scope(tags=("nope",)))
    assert res.paths == [] and res.missing == ["#nope"]


def test_content_dates(resolver: ScopeResolver) -> None:
    october = DayRange(d("2026-10-01"), d("2026-10-31"))
    assert resolver.resolve(Scope(dates=october)).paths == [
        "Clients/Beta.md",  # front matter
        "Journal/2026-10-20.md",  # daily-note name
    ]


def test_edited_dates(resolver: ScopeResolver) -> None:
    year_2025 = DayRange(d("2025-01-01"), d("2025-12-31"))
    assert resolver.resolve(Scope(dates=year_2025, date_kind="edited")).paths == [
        "Ideas/Cafe.md",
        "Pricing.md",
    ]
    assert resolver.resolve(Scope(dates=year_2025)).paths == []  # no content date in 2025


def test_named_notes_and_ambiguity(resolver: ScopeResolver) -> None:
    res = resolver.resolve(Scope(notes=("acme", "Pricing")))
    assert res.paths == ["Clients/Acme.md", "Pricing.md"] and not res.ambiguous


def test_links(resolver: ScopeResolver) -> None:
    assert resolver.resolve(Scope(linked_from=("Acme",))).paths == ["Pricing.md"]
    assert resolver.resolve(Scope(links_to=("Pricing",))).paths == ["Clients/Acme.md"]
    assert resolver.resolve(Scope(links_to=("Beta",))).paths == ["Pricing.md"]
