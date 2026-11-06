"""Index schema 5: headings, note dates, words, private flag (PLAN_vault_agent P30.8)."""

import sqlite3
from pathlib import Path

import pytest

from paper_pile.core.index import SCHEMA_VERSION, Index, note_dates
from paper_pile.core.parser import FrontMatter
from paper_pile.core.vault import Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.create_note(
        "a.md",
        "---\ndate: 2025-10-03\ncreated: '2025-09-30T08:00'\n---\n# Alpha\n\nOne two three.\n\n"
        "## Part\n\n[[b]] text\n\n```\n# not a heading\n```\n",
    )
    v.create_note("b.md", "---\nai: false\ntags: [x]\n---\nSecret words.\n")
    v.create_note("c/d.md", "Underlined\n===\n\nplain #topic\n")
    v.create_note("e.txt", "# no headings in txt\n")
    return v


def test_schema_version() -> None:
    assert SCHEMA_VERSION == "5"


def test_headings_indexed(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    assert [(h.level, h.text, h.line) for h in ix.headings_of("a.md")] == [
        (1, "Alpha", 5),
        (2, "Part", 9),
    ]
    assert [h.text for h in ix.headings_of("c/d.md")] == ["Underlined"]
    assert ix.headings_of("e.txt") == []


def test_dates_indexed_and_queried(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    assert [(d.kind, d.day) for d in ix.dates_of("a.md")] == [
        ("date", "2025-10-03"),
        ("created", "2025-09-30"),
    ]
    assert [(d.path, d.kind) for d in ix.dated_notes("2025-10-01", "2025-10-31")] == [
        ("a.md", "date")
    ]
    assert ix.dated_notes("2024-01-01", "2024-12-31") == []


def test_note_dates_values() -> None:
    import datetime as dt

    fm = FrontMatter(
        "",
        {
            "date": dt.date(2025, 1, 2),
            "created": dt.datetime(2025, 1, 1, 9, 0),
            "updated": "2025-13-40",  # not a date
            "modified": "soon",
        },
    )
    assert note_dates(fm) == [("date", "2025-01-02"), ("created", "2025-01-01")]
    assert note_dates(None) == []


def test_words_and_private(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    rows = {r.path: r for r in ix.note_rows()}
    assert rows["b.md"].private and not rows["a.md"].private
    assert rows["a.md"].words > 3
    assert [r.path for r in ix.note_rows(["c/d.md", "zz.md"])] == ["c/d.md"]


def test_update_replaces_headings_and_dates(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    vault.write_text("a.md", "# New\n")
    ix.update_note("a.md")
    assert [h.text for h in ix.headings_of("a.md")] == ["New"]
    assert ix.dates_of("a.md") == []
    vault.write_text("b.md", "now public\n")
    ix.update_note("b.md")
    assert not {r.path: r for r in ix.note_rows()}["b.md"].private


def test_tags_and_links_stats(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    assert ix.tag_pairs() == [("b.md", "x"), ("c/d.md", "topic")]
    assert ix.tagged_paths() == {"b.md", "c/d.md"}
    out, keys = ix.link_stats()
    assert out["a.md"] == 1 and out["b.md"] == 0
    assert "b" in keys


def test_schema_4_database_is_rebuilt(vault: Vault) -> None:
    ix = Index(vault)
    ix.sync()
    ix.close()
    db = sqlite3.connect(vault.root / ".paper-pile" / "index.db")
    db.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
    db.commit()
    db.close()
    ix = Index(vault)
    assert ix.paths() == []  # discarded …
    ix.sync()
    assert [h.text for h in ix.headings_of("a.md")] == ["Alpha", "Part"]  # … and rebuilt
