"""Saved vault searches (PLAN_vault_agent P30.41)."""

from pathlib import Path

from paper_pile.core.ai.vault.searches import (
    MAX_SEARCHES,
    remove_search,
    save_search,
    saved_searches,
    searches_path,
)


def test_save_list_remove(tmp_path: Path) -> None:
    assert saved_searches(tmp_path) == []
    assert save_search(tmp_path, "  where are my   social business notes? ")
    assert save_search(tmp_path, "how many notes have no tags")
    assert not save_search(tmp_path, "   ")
    assert saved_searches(tmp_path) == [
        "how many notes have no tags",
        "where are my social business notes?",
    ]
    save_search(tmp_path, "where are my social business notes?")  # a repeat moves up
    assert saved_searches(tmp_path)[0] == "where are my social business notes?"
    remove_search(tmp_path, "how many notes have no tags")
    assert saved_searches(tmp_path) == ["where are my social business notes?"]


def test_cap_and_corrupt_file(tmp_path: Path) -> None:
    for i in range(MAX_SEARCHES + 5):
        save_search(tmp_path, f"q{i}")
    assert len(saved_searches(tmp_path)) == MAX_SEARCHES
    searches_path(tmp_path).write_text("{not json")
    assert saved_searches(tmp_path) == []
