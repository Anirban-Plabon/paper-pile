import os
import stat
from pathlib import Path

import pytest

from paper_pile.core.buffer import NoteBuffer, content_hash, find_recoverable
from paper_pile.core.recovery import RecoveryStore
from paper_pile.core.vault import NotFoundError, Vault


@pytest.fixture
def env(tmp_path: Path) -> tuple[Vault, RecoveryStore]:
    root = tmp_path / "vault"
    root.mkdir()
    return Vault(root), RecoveryStore(root)


def test_open_loads_disk_text_and_is_clean(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "hello")
    buf = NoteBuffer.open(vault, rec, "a.md")
    assert buf.text == "hello" and not buf.dirty
    assert rec.pending() == []


def test_open_missing_note_raises(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    with pytest.raises(NotFoundError):
        NoteBuffer.open(vault, rec, "nope.md")


def test_editing_marks_dirty_and_mirrors(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "hello")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("hello world")
    assert buf.dirty
    entry = rec.get("a.md")
    assert entry is not None and entry.text == "hello world"
    assert entry.base_hash == content_hash("hello")
    assert vault.read_text("a.md") == "hello"  # nothing written until save()


def test_undo_back_to_saved_text_is_clean_again(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "hello")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("changed")
    assert rec.get("a.md") is not None
    buf.set_text("hello")
    assert not buf.dirty and rec.get("a.md") is None


def test_save_writes_atomically_and_clears_recovery(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "hello")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("line one\r\nline two")
    assert buf.save() is True
    assert vault.read_text("a.md") == "line one\r\nline two"
    assert not buf.dirty and buf.error is None and rec.pending() == []
    assert buf.save() is True  # nothing to do


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_failed_save_keeps_text_dirty_and_recoverable(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("d/a.md", "hello")
    buf = NoteBuffer.open(vault, rec, "d/a.md")
    buf.set_text("precious unsaved words")
    folder = vault.root / "d"
    folder.chmod(stat.S_IRUSR | stat.S_IXUSR)  # read-only: the atomic temp file cannot be made
    try:
        assert buf.save() is False
        assert buf.dirty and buf.error
        assert buf.text == "precious unsaved words"
        assert rec.get("d/a.md").text == "precious unsaved words"  # type: ignore[union-attr]
    finally:
        folder.chmod(stat.S_IRWXU)
    assert vault.read_text("d/a.md") == "hello"  # original untouched
    assert buf.save() is True  # works again once the problem is gone
    assert vault.read_text("d/a.md") == "precious unsaved words" and rec.pending() == []


def test_save_does_not_resurrect_a_note_deleted_on_disk(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "hello")
    buf = NoteBuffer.open(vault, rec, "a.md")
    (vault.root / "a.md").unlink()  # removed behind our back
    buf.set_text("my unsaved text")
    assert buf.save() is False
    assert "deleted or moved" in (buf.error or "")
    assert not vault.exists("a.md")
    assert rec.get("a.md").text == "my unsaved text"  # type: ignore[union-attr]


def test_restore_over_existing_note(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "disk version")
    buf = NoteBuffer.open(vault, rec, "a.md", recovered="recovered version")
    assert buf.text == "recovered version" and buf.dirty
    assert buf.save() is True
    assert vault.read_text("a.md") == "recovered version"


def test_restore_recreates_a_note_whose_file_is_gone(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    buf = NoteBuffer.open(vault, rec, "gone/n.md", recovered="rescued")
    assert buf.dirty and not vault.exists("gone/n.md")
    assert buf.save() is True
    assert vault.read_text("gone/n.md") == "rescued"


def test_rename_follows_the_note(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("old.md", "x")
    buf = NoteBuffer.open(vault, rec, "old.md")
    buf.set_text("x edited")
    vault.rename("old.md", "new.md")
    buf.rename("new.md")
    assert [e.path for e in rec.pending()] == ["new.md"]
    assert buf.save() is True
    assert vault.read_text("new.md") == "x edited" and rec.pending() == []


def test_discard_forgets_the_buffer(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "x")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("y")
    buf.discard()
    assert rec.pending() == []


# ---- find_recoverable ------------------------------------------------------------------


def test_find_recoverable_offers_only_real_differences(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("changed.md", "disk")
    vault.create_note("same.md", "identical")
    rec.write("changed.md", "unsaved", None)
    rec.write("same.md", "identical", None)  # already saved: stale entry
    rec.write("deleted.md", "orphaned text", None)  # note is gone, text is not
    rec.write("../escape.md", "bad", None)  # not a valid vault path
    offered = find_recoverable(vault, rec)
    assert sorted(e.path for e in offered) == ["changed.md", "deleted.md"]
    assert rec.get("same.md") is None  # stale entry was cleaned up
    assert rec.get("../escape.md") is not None  # unknown entries are never deleted blindly


def test_opening_a_clean_note_keeps_a_pending_recovery_draft(
    env: tuple[Vault, RecoveryStore],
) -> None:
    vault, rec = env
    vault.create_note("a.md", "disk text")
    rec.write("a.md", "older unsaved draft", None)  # left behind by a crash
    buf = NoteBuffer.open(vault, rec, "a.md")  # e.g. a restored tab, or "Later" then open
    assert buf.text == "disk text" and not buf.dirty
    entry = rec.get("a.md")
    assert entry is not None and entry.text == "older unsaved draft"
    assert [e.path for e in find_recoverable(vault, rec)] == ["a.md"]  # still offered
