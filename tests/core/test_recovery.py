import json
from pathlib import Path

from paper_pile.core.recovery import RecoveryStore


def test_write_get_clear(tmp_path: Path) -> None:
    store = RecoveryStore(tmp_path)
    assert store.get("a.md") is None and store.pending() == []
    store.write("a.md", "unsaved ✓", "abc")
    entry = store.get("a.md")
    assert entry is not None
    assert (entry.path, entry.text, entry.base_hash) == ("a.md", "unsaved ✓", "abc")
    assert store.pending() == [entry]
    store.clear("a.md")
    assert store.get("a.md") is None and store.pending() == []
    store.clear("a.md")  # clearing twice is fine


def test_one_file_per_note_and_overwrite(tmp_path: Path) -> None:
    store = RecoveryStore(tmp_path)
    store.write("a.md", "one", None)
    store.write("a.md", "two", None)
    store.write("d/b.md", "bee", "h")
    assert sorted(e.path for e in store.pending()) == ["a.md", "d/b.md"]
    assert store.get("a.md").text == "two"  # type: ignore[union-attr]
    assert len(list(store.dir.glob("*.json"))) == 2


def test_pending_is_oldest_first(tmp_path: Path) -> None:
    store = RecoveryStore(tmp_path)
    store.write("first.md", "1", None)
    store.write("second.md", "2", None)
    assert [e.path for e in store.pending()] == ["first.md", "second.md"]


def test_corrupt_files_are_skipped_not_deleted(tmp_path: Path) -> None:
    store = RecoveryStore(tmp_path)
    store.write("ok.md", "fine", None)
    (store.dir / "garbage.json").write_text("{not json")
    (store.dir / "wrongshape.json").write_text(json.dumps({"path": "x.md"}))
    assert [e.path for e in store.pending()] == ["ok.md"]
    assert (store.dir / "garbage.json").exists()  # left for a human to look at


def test_write_failure_does_not_raise(tmp_path: Path) -> None:
    blocker = tmp_path / ".paper-pile"
    blocker.write_text("a file where the folder should be")
    RecoveryStore(tmp_path).write("a.md", "x", None)  # no exception
