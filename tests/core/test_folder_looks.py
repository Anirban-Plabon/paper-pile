import json
from pathlib import Path

from paper_pile.core.folder_looks import FOLDER_COLORS, FOLDER_ICONS, FolderLooks


def test_palette_sizes() -> None:
    assert len(FOLDER_COLORS) == 8  # 2 rows × 4
    assert len(FOLDER_ICONS) == 16  # 4 rows × 4
    assert len(set(FOLDER_ICONS)) == 16


def test_icons_exist_in_the_vendored_set() -> None:
    from paper_pile.gui.icons import has_icon

    assert all(has_icon(name) for name in FOLDER_ICONS)


def test_defaults(tmp_path: Path) -> None:
    looks = FolderLooks(tmp_path)
    assert looks.color("a") == ""
    assert looks.icon("a") == "folder"
    assert looks.pinned() == []


def test_set_and_reload(tmp_path: Path) -> None:
    looks = FolderLooks(tmp_path)
    assert looks.set_color("a", "red")
    assert looks.set_icon("a", "star")
    assert looks.set_pinned("a", True)
    assert not looks.set_pinned("a", True)
    again = FolderLooks(tmp_path)
    assert (again.color("a"), again.icon("a"), again.pinned()) == ("red", "star", ["a"])


def test_unknown_values_change_nothing(tmp_path: Path) -> None:
    looks = FolderLooks(tmp_path)
    assert not looks.set_color("a", "chartreuse")
    assert not looks.set_icon("a", "rm-rf")
    assert not (tmp_path / ".paper-pile" / "folders.json").exists()


def test_back_to_default_drops_entry(tmp_path: Path) -> None:
    looks = FolderLooks(tmp_path)
    looks.set_color("a", "blue")
    looks.set_icon("a", "code")
    looks.set_color("a", "")
    looks.set_icon("a", "folder")
    data = json.loads((tmp_path / ".paper-pile" / "folders.json").read_text())
    assert data["looks"] == {}
    looks.set_color("b", "green")
    assert looks.reset("b") and looks.color("b") == ""


def test_rename_moves_children(tmp_path: Path) -> None:
    looks = FolderLooks(tmp_path)
    looks.set_color("a", "red")
    looks.set_icon("a/b", "star")
    looks.set_color("ab", "blue")  # same prefix, not inside
    looks.set_pinned("a/b", True)
    assert looks.renamed("a", "x")
    assert looks.color("x") == "red" and looks.icon("x/b") == "star"
    assert looks.color("ab") == "blue"
    assert looks.pinned() == ["x/b"]
    assert not looks.renamed("nothing", "here")


def test_delete_drops_children(tmp_path: Path) -> None:
    looks = FolderLooks(tmp_path)
    looks.set_color("a/b", "red")
    looks.set_pinned("a", True)
    looks.set_pinned("ab", True)
    assert looks.deleted("a")
    assert looks.color("a/b") == "" and looks.pinned() == ["ab"]


def test_bad_file_is_ignored(tmp_path: Path) -> None:
    store = tmp_path / ".paper-pile"
    store.mkdir()
    (store / "folders.json").write_text(
        json.dumps({"looks": {"a": {"color": "nope", "icon": "star"}, "b": 3}, "pinned": [1, "a"]})
    )
    looks = FolderLooks(tmp_path)
    assert looks.color("a") == "" and looks.icon("a") == "star"
    assert looks.pinned() == ["a"]
    (store / "folders.json").write_text("not json")
    assert FolderLooks(tmp_path).pinned() == []
