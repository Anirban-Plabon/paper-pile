import os
import stat
from pathlib import Path

import pytest

from paper_pile.core.buffer import NoteBuffer, Outcome, content_hash, find_recoverable
from paper_pile.core.recovery import RecoveryStore
from paper_pile.core.vault import NotFoundError, Vault, VaultError


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


# ---- sync_with_disk: changes made outside the app ----------------------------------------


def _external_write(vault: Vault, rel: str, text: str) -> None:
    (vault.root / rel).write_text(text, encoding="utf-8")  # what a terminal or another editor does


def test_unchanged_disk_is_a_noop_and_so_is_the_echo_of_our_own_save(
    env: tuple[Vault, RecoveryStore],
) -> None:
    vault, rec = env
    vault.create_note("a.md", "v1")
    buf = NoteBuffer.open(vault, rec, "a.md")
    assert buf.sync_with_disk() is Outcome.UNCHANGED
    buf.set_text("v2")
    assert buf.save()
    assert buf.sync_with_disk() is Outcome.UNCHANGED  # the watcher reports our own write too
    assert buf.text == "v2" and not buf.dirty and buf.conflict is None


def test_touch_without_a_content_change_is_unchanged(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "same")
    buf = NoteBuffer.open(vault, rec, "a.md")
    _external_write(vault, "a.md", "same")
    assert buf.sync_with_disk() is Outcome.UNCHANGED


def test_clean_buffer_takes_an_outside_change_silently(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "old")
    buf = NoteBuffer.open(vault, rec, "a.md")
    _external_write(vault, "a.md", "new from the terminal")
    assert buf.sync_with_disk() is Outcome.RELOADED
    assert buf.text == "new from the terminal" and not buf.dirty and buf.conflict is None
    assert buf.sync_with_disk() is Outcome.UNCHANGED  # and it is now the known state
    assert vault.read_text("a.md") == "new from the terminal"  # we never wrote anything


def test_dirty_buffer_and_a_different_disk_version_is_a_conflict(
    env: tuple[Vault, RecoveryStore],
) -> None:
    vault, rec = env
    vault.create_note("a.md", "base")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("my edit")
    _external_write(vault, "a.md", "their edit")
    assert buf.sync_with_disk() is Outcome.CONFLICT
    assert buf.conflict is not None and buf.conflict.text == "their edit"
    assert buf.text == "my edit" and buf.dirty  # nothing lost on either side
    assert vault.read_text("a.md") == "their edit"


def test_a_conflict_blocks_saving_so_nothing_is_overwritten(
    env: tuple[Vault, RecoveryStore],
) -> None:
    vault, rec = env
    vault.create_note("a.md", "base")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("my edit")
    _external_write(vault, "a.md", "their edit")
    buf.sync_with_disk()
    assert buf.save() is False
    assert "changed on disk" in (buf.error or "")
    assert vault.read_text("a.md") == "their edit"
    assert rec.get("a.md").text == "my edit"  # type: ignore[union-attr]


def test_a_later_outside_change_updates_the_pending_conflict(
    env: tuple[Vault, RecoveryStore],
) -> None:
    vault, rec = env
    vault.create_note("a.md", "base")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("mine")
    _external_write(vault, "a.md", "theirs 1")
    buf.sync_with_disk()
    _external_write(vault, "a.md", "theirs 2")
    assert buf.sync_with_disk() is Outcome.CONFLICT
    assert buf.conflict is not None and buf.conflict.text == "theirs 2"


def test_the_conflict_clears_itself_if_the_disk_goes_back(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "base")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("mine")
    _external_write(vault, "a.md", "theirs")
    buf.sync_with_disk()
    _external_write(vault, "a.md", "base")  # reverted outside
    assert buf.sync_with_disk() is Outcome.UNCHANGED and buf.conflict is None
    assert buf.save() is True and vault.read_text("a.md") == "mine"


def test_typing_exactly_what_someone_wrote_is_not_a_conflict(
    env: tuple[Vault, RecoveryStore],
) -> None:
    vault, rec = env
    vault.create_note("a.md", "base")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("identical")
    _external_write(vault, "a.md", "identical")
    assert buf.sync_with_disk() is Outcome.UNCHANGED
    assert not buf.dirty and buf.conflict is None and rec.pending() == []


def test_keep_mine_overwrites_on_the_next_save(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "base")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("mine")
    _external_write(vault, "a.md", "theirs")
    buf.sync_with_disk()
    buf.keep_mine()
    assert buf.conflict is None and buf.dirty and buf.text == "mine"
    assert buf.save() is True
    assert vault.read_text("a.md") == "mine" and rec.pending() == []


def test_load_theirs_drops_the_edits_and_adopts_the_disk(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "base")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("mine")
    _external_write(vault, "a.md", "theirs")
    buf.sync_with_disk()
    buf.load_theirs()
    assert buf.text == "theirs" and not buf.dirty and buf.conflict is None
    assert rec.pending() == [] and vault.read_text("a.md") == "theirs"


def test_clean_note_deleted_outside_is_reported_gone(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "text")
    buf = NoteBuffer.open(vault, rec, "a.md")
    (vault.root / "a.md").unlink()
    assert buf.sync_with_disk() is Outcome.GONE


def test_dirty_note_deleted_outside_is_a_conflict_that_can_recreate_it(
    env: tuple[Vault, RecoveryStore],
) -> None:
    vault, rec = env
    vault.create_note("a.md", "text")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("my unsaved words")
    (vault.root / "a.md").unlink()
    assert buf.sync_with_disk() is Outcome.CONFLICT_GONE
    assert buf.conflict is not None and buf.conflict.text is None
    assert buf.save() is False and not vault.exists("a.md")  # never silently resurrected
    buf.keep_mine()
    assert buf.save() is True and vault.read_text("a.md") == "my unsaved words"


def test_load_theirs_is_not_offered_for_a_deleted_note(env: tuple[Vault, RecoveryStore]) -> None:
    vault, rec = env
    vault.create_note("a.md", "text")
    buf = NoteBuffer.open(vault, rec, "a.md")
    buf.set_text("mine")
    (vault.root / "a.md").unlink()
    buf.sync_with_disk()
    buf.load_theirs()  # no-op
    assert buf.text == "mine" and buf.conflict is not None


def test_a_restored_draft_of_a_note_that_never_existed_is_left_alone(
    env: tuple[Vault, RecoveryStore],
) -> None:
    vault, rec = env
    buf = NoteBuffer.open(vault, rec, "gone/n.md", recovered="rescued")
    assert buf.sync_with_disk() is Outcome.UNCHANGED and buf.conflict is None


def test_an_unreadable_outside_write_does_not_crash_or_change_the_buffer(
    env: tuple[Vault, RecoveryStore],
) -> None:
    vault, rec = env
    vault.create_note("a.md", "text")
    buf = NoteBuffer.open(vault, rec, "a.md")
    (vault.root / "a.md").write_bytes(b"\xff\xfe\x00 not utf-8")
    assert buf.sync_with_disk() is Outcome.UNCHANGED
    assert buf.text == "text"


# ---- Vault.stash_text -------------------------------------------------------------------


def test_stash_text_keeps_a_version_in_the_trash(env: tuple[Vault, RecoveryStore]) -> None:
    vault, _ = env
    where = vault.stash_text("notes/idea.md", "the losing side", "changed on disk")
    assert where.startswith(".trash/") and where.endswith("/notes/idea (changed on disk).md")
    assert (vault.root / where).read_text() == "the losing side"
    assert list(vault.walk_notes()) == []  # trash stays invisible to the app


def test_stash_text_never_overwrites(env: tuple[Vault, RecoveryStore]) -> None:
    vault, _ = env
    a = vault.stash_text("n.md", "one", "mine")
    b = vault.stash_text("n.md", "two", "mine")
    assert (
        a != b and (vault.root / a).read_text() == "one" and (vault.root / b).read_text() == "two"
    )


def test_stash_text_refuses_unsafe_paths(env: tuple[Vault, RecoveryStore]) -> None:
    vault, _ = env
    with pytest.raises(VaultError):
        vault.stash_text("../escape.md", "x", "mine")


def test_resolving_or_reloading_clears_an_old_save_failure(
    env: tuple[Vault, RecoveryStore],
) -> None:
    """A failed save leaves `error` set; once the text it was about is gone (reloaded from disk,
    or the user chose a side) the note must not keep showing 'Save failed'."""
    vault, rec = env
    for how in ("reload", "load_theirs", "keep_mine"):
        name = f"{how}.md"
        vault.create_note(name, "base")
        buf = NoteBuffer.open(vault, rec, name)
        buf.error = "disk full"  # as left by a failed save
        if how == "reload":
            _external_write(vault, name, "theirs")
            assert buf.sync_with_disk() is Outcome.RELOADED
        else:
            buf.set_text("mine")
            _external_write(vault, name, "theirs")
            assert buf.sync_with_disk() is Outcome.CONFLICT
            getattr(buf, how)()
        assert buf.error is None, how
