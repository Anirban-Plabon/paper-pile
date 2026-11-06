"""Vault agent, the rest of M7 / MC (P30.30, P30.34, P30.35, P30.45–P30.48): text for a note,
citations and results following renames, an answer to a review that is no longer open."""

import asyncio
from pathlib import Path

from paper_pile.core.ai.chats import (
    SavedChat,
    SavedTurn,
    load_chat,
    moved_path,
    rename_in_chats,
    rename_in_turns,
    save_chat,
)
from paper_pile.core.ai.vault.cards import Card, CardStore, rename_tree
from paper_pile.core.ai.vault.cite import answer_for_note
from paper_pile.core.ai.vault.results import ResultItem, ResultSet
from paper_pile.core.ai.vault.session import EXPIRED, VaultSession

CITES = [
    {"n": 1, "path": "R/Yunus.md", "title": "Yunus", "heading": ""},
    {"n": 2, "path": "R/Bank.md", "title": "Bank", "heading": "Groups"},
]


def link(path: str) -> str:
    return path.rsplit("/", 1)[-1][:-3]


def test_answer_for_note() -> None:
    text = (
        "Found 2 notes.\n\n1. [**Yunus**](<pp-note:R/Yunus.md>) (R): founder\n\n"
        "Grameen lends [1]. Groups lend [1, 2].\n\nSources: [1] Yunus · [2] Bank § Groups\n\n"
        "_1 citation could not be verified._"
    )
    out = answer_for_note(text, CITES, link)
    assert "Sources:" not in out and "could not be verified" not in out
    assert "1. [[Yunus]] (R): founder" in out
    assert "Grameen lends ([[Yunus]]). Groups lend ([[Yunus]], [[Bank#Groups]])." in out
    assert "pp-note" not in out


def test_moved_path() -> None:
    assert moved_path("R/Yunus.md", "R/Yunus.md", "People/Yunus.md") == "People/Yunus.md"
    assert moved_path("R/Yunus.md", "R", "Research") == "Research/Yunus.md"
    assert moved_path("Rx/Yunus.md", "R", "Research") == "Rx/Yunus.md"  # only under it


def test_renames_follow_into_turns_and_saved_chats(tmp_path: Path) -> None:
    turns = [
        SavedTurn(
            "assistant",
            "a [1]",
            sources=["R/Yunus.md", "Other.md"],
            vault={
                "kind": "answer",
                "cites": [dict(c) for c in CITES],
                "review": [{"n": 1, "path": "R/Bank.md"}],
                "chips": [{"label": "Open all", "open": ["R/Yunus.md"]}],
            },
        )
    ]
    assert rename_in_turns(turns, "R", "Research")
    t = turns[0]
    assert t.sources == ["Research/Yunus.md", "Other.md"]
    assert [c["path"] for c in t.vault["cites"]] == ["Research/Yunus.md", "Research/Bank.md"]
    assert t.vault["review"][0]["path"] == "Research/Bank.md"
    assert t.vault["chips"][0]["open"] == ["Research/Yunus.md"]
    assert not rename_in_turns(turns, "Nope", "X")
    save_chat(tmp_path, SavedChat("c1", "t", 1.0, 2.0, turns))
    save_chat(tmp_path, SavedChat("c2", "t", 1.0, 2.0, [SavedTurn("user", "q")]))
    assert rename_in_chats(tmp_path, "Research/Yunus.md", "People/Yunus.md") == 1  # only c1
    loaded = load_chat(tmp_path, "c1")
    assert loaded is not None and loaded.turns[0].vault["cites"][0]["path"] == "People/Yunus.md"


def test_card_store_follows_a_folder_rename(tmp_path: Path) -> None:
    store = CardStore(tmp_path)
    store.put(Card("R/Yunus.md", "h1", "About Yunus.", ()))
    store.put(Card("Rx/Other.md", "h2", "Other.", ()))
    rename_tree(store, "R", "Research")
    assert store.get("Research/Yunus.md", "h1") is not None
    assert store.get("R/Yunus.md", "h1") is None
    assert store.get("Rx/Other.md", "h2") is not None  # a sibling with the same start stays


class _Engine:
    """Just enough engine for the session's rename and expired-answer paths."""

    def __init__(self, turns: list[SavedTurn]) -> None:
        self.turns = turns
        self.index = None  # no agent: handle() answers only what needs no model
        self.config = None


def test_session_follows_renames_and_explains_an_expired_review() -> None:
    session = VaultSession(_Engine([]))  # type: ignore[arg-type]
    session.last = ResultSet("q", [ResultItem("R/Yunus.md", "Yunus")])
    session.renamed("R", "Research")
    assert session.last.paths == ["Research/Yunus.md"]

    turns = [
        SavedTurn("user", "remove X"),
        SavedTurn("assistant", "review", vault={"kind": "review"}),
        SavedTurn("user", "Apply all"),
    ]
    session = VaultSession(_Engine(turns))  # type: ignore[arg-type]
    # explained without the agent (no index here): the question it answers is gone
    turn = asyncio.run(session.handle("Apply all", scopes=[], attached=False))
    assert turn is not None and turn.text == EXPIRED
