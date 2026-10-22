import json
from pathlib import Path

import pytest

from paper_pile.core.ai.chats import (
    SavedChat,
    SavedTurn,
    chat_title,
    chats_folder,
    delete_chat,
    list_chats,
    load_chat,
    new_chat_id,
    save_chat,
)
from paper_pile.core.vault import Vault


def _chat(chat_id: str, updated: float, text: str = "hello") -> SavedChat:
    turns = [SavedTurn("user", text, "[[a]]"), SavedTurn("assistant", "hi", summary="ctx")]
    return SavedChat(chat_id, chat_title(turns), 1.0, updated, turns)


def test_round_trip(tmp_path: Path) -> None:
    chat = _chat(new_chat_id(), 5.0)
    save_chat(chats_folder(tmp_path), chat)
    assert load_chat(chats_folder(tmp_path), chat.id) == chat
    assert (tmp_path / ".memory" / f"{chat.id}.json").is_file()


def test_list_newest_first_and_skips_bad_files(tmp_path: Path) -> None:
    save_chat(chats_folder(tmp_path), _chat("old", 1.0))
    save_chat(chats_folder(tmp_path), _chat("new", 9.0))
    folder = tmp_path / ".memory"
    (folder / "broken.json").write_text("{not json")
    (folder / "empty.json").write_text(json.dumps({"turns": []}))
    (folder / "odd.json").write_text(json.dumps({"turns": [{"role": "x", "text": "?"}]}))
    assert [c.id for c in list_chats(chats_folder(tmp_path))] == ["new", "old"]


def test_list_without_folder(tmp_path: Path) -> None:
    assert list_chats(chats_folder(tmp_path)) == []


def test_title_is_first_user_line_cut() -> None:
    assert chat_title([SavedTurn("user", "  what\nis  this ")]) == "what is this"
    long = chat_title([SavedTurn("user", "x" * 100)])
    assert len(long) == 60 and long.endswith("…")
    assert chat_title([SavedTurn("assistant", "hi")]) == ""


def test_bad_ids_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_chat(chats_folder(tmp_path), _chat("../escape", 1.0))
    assert load_chat(chats_folder(tmp_path), "../escape") is None


def test_delete_goes_to_trash(tmp_path: Path) -> None:
    save_chat(chats_folder(tmp_path), _chat("gone", 1.0))
    delete_chat(Vault(tmp_path), chats_folder(tmp_path), "gone")
    assert list_chats(chats_folder(tmp_path)) == []
    assert list((tmp_path / ".trash").rglob("gone.json"))
    delete_chat(Vault(tmp_path), chats_folder(tmp_path), "gone")  # already gone: nothing happens


def test_ago() -> None:
    import time

    from paper_pile.core.ai.chats import ago

    now = time.mktime((2026, 10, 21, 15, 0, 0, 0, 0, -1))
    assert ago(now - 10, now) == "just now"
    assert ago(now - 300, now) == "5 min ago"
    assert ago(now - 3 * 3600, now) == "3 h ago"
    assert ago(now - 20 * 3600, now) == "yesterday"
    assert ago(now - 9 * 86400, now) == "Oct 12"
    assert ago(now - 400 * 86400, now).endswith(", 2025")


def test_filter_by_words_in_title_or_messages_and_by_day() -> None:
    from datetime import date, datetime

    from paper_pile.core.ai.chats import filter_chats

    def at(day: str) -> float:
        return datetime.fromisoformat(f"{day}T12:00:00").timestamp()

    a = _chat("a", at("2026-10-01"), "Python lists")
    b = _chat("b", at("2026-10-10"), "Cooking rice")
    b.turns.append(SavedTurn("assistant", "Rinse the rice with python-free water"))
    c = _chat("c", at("2026-10-20"), "Python decorators")
    chats = [a, b, c]
    assert [x.id for x in filter_chats(chats, "python")] == ["a", "b", "c"]
    assert [x.id for x in filter_chats(chats, "PYTHON decorators")] == ["c"]
    assert [x.id for x in filter_chats(chats, "", date(2026, 10, 10), date(2026, 10, 20))] == [
        "b",
        "c",
    ]
    assert [x.id for x in filter_chats(chats, "", None, date(2026, 10, 1))] == ["a"]
    assert [x.id for x in filter_chats(chats, "python", date(2026, 10, 2))] == ["b", "c"]


def test_delete_chats_moves_each_to_the_trash(tmp_path: Path) -> None:
    from paper_pile.core.ai.chats import delete_chats

    for chat_id in ("a", "b", "c"):
        save_chat(chats_folder(tmp_path), _chat(chat_id, 1.0))
    folder = chats_folder(tmp_path)
    assert delete_chats(Vault(tmp_path), folder, ["a", "c", "missing"]) == 3  # missing: no error
    assert [c.id for c in list_chats(chats_folder(tmp_path))] == ["b"]
    assert len(list((tmp_path / ".trash").rglob("*.json"))) == 2
    assert delete_chats(Vault(tmp_path), folder, ["../x"]) == 0  # a bad id is skipped


def test_expired_chats() -> None:
    from paper_pile.core.ai.chats import expired_chats

    day = 86400.0
    chats = [_chat("old", 0.0), _chat("new", 9 * day)]
    assert [c.id for c in expired_chats(chats, 5, 10 * day)] == ["old"]
    assert expired_chats(chats, 0, 10 * day) == []  # 0 = keep forever


def test_chat_markdown() -> None:
    from paper_pile.core.ai.chats import chat_markdown

    chat = _chat("a", 5.0, "What is $x$?")
    text = chat_markdown(chat, "Ana")
    assert text.startswith("# What is $x$?\n\n*")
    assert "2 messages*" in text
    assert "### Ana\n\n*Attached: [[a]]*\n\nWhat is $x$?" in text
    assert text.endswith("### Assistant\n\nhi\n")
    assert "### You" in chat_markdown(chat)


def test_chat_note_name() -> None:
    from paper_pile.core.ai.chats import chat_note_name

    assert chat_note_name(_chat("a", 1.0, "What is a/b: [[x]] #tag?")) == "What is a b x tag"
    assert chat_note_name(_chat("a", 1.0, "...hidden")) == "hidden"
    assert chat_note_name(_chat("a", 1.0, "???")) == "Chat"


def test_chats_folder_from_the_setting(tmp_path: Path) -> None:
    assert chats_folder(tmp_path) == tmp_path / ".memory"
    assert chats_folder(tmp_path, "  AI/memories ") == tmp_path / "AI" / "memories"
    assert chats_folder(tmp_path, "/data/chats") == Path("/data/chats")
    assert chats_folder(tmp_path, "~/chats") == Path.home() / "chats"


def test_move_chats_never_overwrites(tmp_path: Path) -> None:
    from paper_pile.core.ai.chats import move_chats

    old, new = chats_folder(tmp_path), tmp_path / "elsewhere"
    for chat_id in ("a", "b"):
        save_chat(old, _chat(chat_id, 1.0))
    save_chat(new, _chat("b", 9.0, "kept"))
    assert move_chats(old, new) == 1
    assert sorted(c.id for c in list_chats(new)) == ["a", "b"]
    assert load_chat(new, "b").title == "kept"  # type: ignore[union-attr]
    assert [c.id for c in list_chats(old)] == ["b"]  # the clash stays where it was
    assert move_chats(new, new) == 0


def test_delete_from_a_folder_outside_the_vault(tmp_path: Path) -> None:
    vault, outside = tmp_path / "vault", tmp_path / "outside"
    vault.mkdir()
    save_chat(outside, _chat("x", 1.0))
    delete_chat(Vault(vault), outside, "x")
    assert list_chats(outside) == []
    assert list((vault / ".trash").rglob("x.json"))
