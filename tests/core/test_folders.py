from pathlib import Path

from paper_pile.core.folders import is_vault, start_folder, subfolders


def test_subfolders_sorted_visible_only(tmp_path: Path) -> None:
    for name in ("beta", "Alpha", ".hidden", "gamma"):
        (tmp_path / name).mkdir()
    (tmp_path / "note.md").write_text("x")
    assert [p.name for p in subfolders(tmp_path)] == ["Alpha", "beta", "gamma"]


def test_subfolders_of_missing_folder_is_empty(tmp_path: Path) -> None:
    assert subfolders(tmp_path / "nope") == []


def test_start_folder_is_the_vaults_parent_else_home(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    assert start_folder(vault) == tmp_path
    assert start_folder(None) == Path.home()


def test_is_vault(tmp_path: Path) -> None:
    assert not is_vault(tmp_path)
    (tmp_path / ".paper-pile").mkdir()
    assert is_vault(tmp_path)
