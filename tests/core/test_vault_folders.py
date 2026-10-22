from pathlib import Path

import pytest

from paper_pile.core.ai.chats import SavedChat, SavedTurn, list_chats, save_chat
from paper_pile.core.config import Config
from paper_pile.core.vault import PUBLIC_DIRS, InvalidPathError, Vault, is_hidden_part
from paper_pile.core.vault_folders import (
    can_clear,
    clear_folder,
    ensure_folders,
    files_in,
    folder_path,
    move_old_chats,
)


def _config(tmp_path: Path) -> Config:
    return Config(global_path=tmp_path / "config.toml")


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    return root


def test_the_app_folders_are_created(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    ensure_folders(root, _config(tmp_path))
    assert {p.name for p in root.iterdir()} == set(PUBLIC_DIRS)
    assert (root / ".template" / "daily").is_dir()  # daily-note templates live here


def test_daily_templates_folder() -> None:
    from paper_pile.core.vault_folders import daily_templates_folder

    assert daily_templates_folder(".template") == ".template/daily"
    assert daily_templates_folder("Templates/") == "Templates/daily"
    assert daily_templates_folder("") == ""


def test_a_folder_the_user_chose_wins(tmp_path: Path) -> None:
    root, config = _vault(tmp_path), _config(tmp_path)
    config.set("vault.daily_notes_folder", "Journal", "global")
    config.set("vault.templates_folder", "", "global")  # the vault root: nothing to create
    ensure_folders(root, config)
    assert (root / "Journal").is_dir() and not (root / ".daily-notes").exists()
    assert not (root / ".template").exists()


def test_the_app_folders_are_ordinary_vault_folders(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    (root / ".daily-notes").mkdir()
    (root / ".daily-notes" / "2026-10-21.md").write_text("today")
    (root / ".trash").mkdir()
    (root / ".trash" / "old.md").write_text("gone")
    (root / "notes" / ".daily-notes").mkdir(parents=True)  # only at the top level
    (root / "notes" / ".daily-notes" / "x.md").write_text("x")
    vault = Vault(root)
    assert list(vault.walk_notes()) == [".daily-notes/2026-10-21.md"]
    assert vault.read_text(".daily-notes/2026-10-21.md") == "today"
    assert [e.name for e in vault.list_tree("")] == [".daily-notes", "notes"]
    with pytest.raises(InvalidPathError):
        vault.resolve(".trash/old.md")
    with pytest.raises(InvalidPathError):
        vault.resolve("notes/.daily-notes/x.md")
    assert not is_hidden_part(".image", 0) and is_hidden_part(".image", 1)


def test_old_chats_move_into_memory_once(tmp_path: Path) -> None:
    root, config = _vault(tmp_path), _config(tmp_path)
    old = root / ".paper-pile" / "chats"
    turns = [SavedTurn("user", "hi"), SavedTurn("assistant", "hello")]
    save_chat(old, SavedChat("c1", "hi", 1.0, 1.0, turns))
    assert move_old_chats(root, config) == 1
    assert [c.id for c in list_chats(root / ".memory")] == ["c1"]
    assert move_old_chats(root, config) == 0


def test_old_chats_stay_when_the_user_chose_a_folder(tmp_path: Path) -> None:
    root, config = _vault(tmp_path), _config(tmp_path)
    save_chat(root / ".paper-pile" / "chats", SavedChat("c1", "hi", 1.0, 1.0, []))
    config.set("ai.chats_folder", "AI", "global")
    assert move_old_chats(root, config) == 0


def test_clear_moves_everything_to_the_trash(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    folder = root / ".image"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.png").write_bytes(b"x")
    (folder / "sub" / "b.png").write_bytes(b"y")
    assert files_in(folder) == 2
    assert clear_folder(Vault(root), folder) == 2
    assert folder.is_dir() and not any(folder.iterdir())
    trash = root / ".trash"
    trashed = sorted(p.relative_to(trash).parts[1:] for p in trash.rglob("*.png"))
    assert trashed == [(".image", "a.png"), (".image", "sub", "b.png")]


def test_clear_refuses_the_vault_and_the_app_data(tmp_path: Path) -> None:
    root = _vault(tmp_path)
    for bad in (root, tmp_path, root / ".paper-pile", root / ".trash", root / ".trash" / "x"):
        assert not can_clear(root, bad)
    with pytest.raises(ValueError):
        clear_folder(Vault(root), root)
    assert folder_path(root, "vault.templates_folder", "") == root
    assert folder_path(root, "ai.chats_folder", "") == root / ".memory"


def test_clear_a_memories_folder_outside_the_vault(tmp_path: Path) -> None:
    root, outside = _vault(tmp_path), tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "c.json").write_text("{}")
    assert clear_folder(Vault(root), outside) == 1
    assert list((root / ".trash").rglob("elsewhere/c.json"))
