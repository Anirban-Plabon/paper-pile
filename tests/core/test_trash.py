"""The trash: what Vault.delete leaves there, listing it, and restoring (PLAN §4.18)."""

import json
from pathlib import Path
from urllib.parse import unquote

import pytest

from paper_pile.core.trash import MANIFEST, list_trash, restore
from paper_pile.core.vault import TRASH_DIR, Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    root = tmp_path / "v"
    (root / "dir" / "sub").mkdir(parents=True)
    (root / "dir" / "sub" / "n.md").write_text("in a folder")
    (root / "note.md").write_text("![p](.note.assets/p.png)\n")
    (root / ".note.assets").mkdir()
    (root / ".note.assets" / "p.png").write_bytes(b"png")
    (root / ".daily-notes").mkdir()
    (root / ".daily-notes" / "2026-10-22.md").write_text("day")
    return Vault(root)


def test_a_deleted_note_comes_back_with_its_images(vault: Vault) -> None:
    vault.delete("note.md")
    [item] = list_trash(vault)
    assert (item.path, item.is_dir, item.name) == ("note.md", False, "note.md")
    assert item.deleted is not None
    assert restore(vault, item) == "note.md"
    assert (vault.root / ".note.assets" / "p.png").read_bytes() == b"png"
    assert list_trash(vault) == [] and not any((vault.root / TRASH_DIR).iterdir())


def test_a_deleted_folder_is_one_item_and_comes_back_whole(vault: Vault) -> None:
    vault.delete("dir")
    [item] = list_trash(vault)
    assert (item.path, item.is_dir) == ("dir", True)
    restore(vault, item)
    assert (vault.root / "dir" / "sub" / "n.md").read_text() == "in a folder"


def test_a_note_in_a_folder_is_not_mistaken_for_the_folder(vault: Vault) -> None:
    vault.delete("dir/sub/n.md")
    [item] = list_trash(vault)
    assert (item.path, item.is_dir) == ("dir/sub/n.md", False)


def test_taken_place_gets_a_restored_name_and_image_links_follow(vault: Vault) -> None:
    vault.delete("note.md")
    (vault.root / "note.md").write_text("a new note with the old name")
    [item] = list_trash(vault)
    assert restore(vault, item) == "note (restored).md"
    assert vault.read_text("note.md") == "a new note with the old name"
    restored = unquote(vault.read_text("note (restored).md"))
    assert "(.note (restored).assets/p.png)" in restored
    assert (vault.root / ".note (restored).assets" / "p.png").exists()


def test_notes_in_app_folders_and_older_entries_are_listed(vault: Vault) -> None:
    vault.delete(".daily-notes/2026-10-22.md")
    old = vault.root / TRASH_DIR / "2020-01-01T00-00-00-000000" / "x"
    old.mkdir(parents=True)
    (old / "a.md").write_text("old delete, no description")
    (old / ".a.assets").mkdir()
    (old / ".a.assets" / "i.png").write_bytes(b"i")
    paths = [i.path for i in list_trash(vault)]
    assert paths == [".daily-notes/2026-10-22.md", "x/a.md"]  # newest first
    restore(vault, list_trash(vault)[1])
    assert (vault.root / "x" / "a.md").exists() and (vault.root / "x" / ".a.assets").is_dir()


def test_a_broken_description_falls_back_to_listing_notes(vault: Vault) -> None:
    vault.delete("note.md")
    stamp = next((vault.root / TRASH_DIR).iterdir())
    (stamp / MANIFEST).write_text(json.dumps({"path": "gone.md"}))
    assert [i.path for i in list_trash(vault)] == ["note.md"]
