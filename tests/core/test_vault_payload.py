"""Vault answers keep their structure (PLAN_vault_agent M7 / MC): citations numbered once
across steps, chips per kind of answer, saved and read back with the chat; citations found
again after the note changed."""

from pathlib import Path

from paper_pile.core.ai.chats import SavedChat, SavedTurn, load_chat, save_chat
from paper_pile.core.ai.vault.cite import anchor_line, make_sources
from paper_pile.core.ai.vault.reply import Hint, Reply
from paper_pile.core.ai.vault.results import ResultItem, ResultSet
from paper_pile.core.ai.vault.session import chip, cite_rows, hint_chips, relabel


def reply(text: str, n: int) -> Reply:
    parts = [(f"n{i}.md", f"N{i}", "", 1, 2, f"text {i}") for i in range(1, n + 1)]
    return Reply(text, sources=make_sources(parts))


def test_relabel_moves_labels_and_sources() -> None:
    moved = relabel(reply("A [1]. B [1, 2].", 2), 3)
    assert moved.text == "A [4]. B [4, 5]."
    assert [s.n for s in moved.sources] == [4, 5]
    assert relabel(reply("x [1]", 1), 0).text == "x [1]"


def test_cite_rows_and_chips() -> None:
    rows = cite_rows(make_sources([("a.md", "A", "Plan", 3, 5, "The plan is simple.")]))
    assert rows == [
        {
            "n": 1,
            "path": "a.md",
            "title": "A",
            "heading": "Plan",
            "start": 3,
            "end": 5,
            "anchor": "The plan is simple.",
            "excerpt": "The plan is simple.",
        }
    ]
    assert chip("Apply all") == {"label": "Apply all", "send": "Apply all"}
    assert chip("Open all", open_paths=["a.md"]) == {"label": "Open all", "open": ["a.md"]}


def test_hint_chips() -> None:
    r = Reply(
        "x",
        ResultSet("q", [ResultItem("a.md", "A"), ResultItem("b.md", "B")]),
        hints=[
            Hint("Summarise all", "action", "summarise"),
            Hint("Make a table", "action", "extract"),
            Hint("Open all", "action", "open"),
            Hint("Search the whole vault", "scope", ""),
            Hint("Only Research (2)", "scope", "Research"),
            Hint("#marketing", "near", "#marketing"),
            Hint("2 more might be related", "maybe", "maybe"),  # information only
        ],
    )
    assert hint_chips(r, "where is X") == [
        {"label": "Summarise all", "send": "Summarise these notes"},
        {"label": "Make a table", "send": "Make a table of these notes"},
        {"label": "Open all", "open": ["a.md", "b.md"]},
        {"label": "Search the whole vault", "send": "@vault where is X"},
        {"label": "Only Research (2)", "send": "Only the ones in @Research/"},
        {"label": "#marketing", "send": "where is X #marketing"},
    ]


def test_vault_payload_saved_with_the_chat(tmp_path: Path) -> None:
    payload = {"kind": "answer", "cites": [{"n": 1, "path": "a.md"}], "chips": [chip("Undo")]}
    chat = SavedChat(
        "c1",
        "t",
        1.0,
        2.0,
        [SavedTurn("user", "q"), SavedTurn("assistant", "a [1]", vault=payload)],
    )
    save_chat(tmp_path, chat)
    loaded = load_chat(tmp_path, "c1")
    assert loaded is not None and loaded.turns[1].vault == payload and loaded.turns[0].vault == {}


def test_anchor_line() -> None:
    text = "# Plan\n\nIntro.\n\n## Budget\nThe budget is 10k for\nthe year.\n"
    anchor = "The budget is 10k for the year."
    assert anchor_line(text, anchor, 6) == 6  # still there
    moved = (
        "# Plan\n\nNew line.\nAnother.\n\nIntro.\n\n## Budget\nThe budget is 10k for\nthe year.\n"
    )
    assert anchor_line(moved, anchor, 6) == 9  # moved down
    assert anchor_line("# Plan\nall rewritten\n", anchor, 6) is None  # gone
    assert anchor_line(text, "", 2) == 2 and anchor_line(text, "", 99) is None
