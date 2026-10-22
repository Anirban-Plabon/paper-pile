import os
from pathlib import Path

import pytest

from paper_pile.core.vault import (
    ExistsError,
    InvalidPathError,
    NotFoundError,
    TreeEntry,
    Vault,
    VaultError,
    is_plain_text,
    join_rel,
    note_filename,
    validate_name,
)


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    root.mkdir()
    return Vault(root)


def names(entries: list[TreeEntry]) -> list[str]:
    return [e.name + ("/" if e.is_dir else "") for e in entries]


# ---- tree ------------------------------------------------------------------------------


def test_list_tree_filters_and_sorts(vault: Vault) -> None:
    root = vault.root
    (root / "b-folder").mkdir()
    (root / "A-folder").mkdir()
    (root / "zebra.md").write_text("z")
    (root / "Apple.md").write_text("a")
    (root / "notes.TXT").write_text("t")
    (root / "image.png").write_bytes(b"\x89PNG")
    (root / "script.py").write_text("x")
    (root / ".hidden.md").write_text("h")
    (root / ".paper-pile").mkdir()
    (root / ".trash").mkdir()
    (root / ".apple.assets").mkdir()
    assert names(vault.list_tree()) == [
        "A-folder/",
        "b-folder/",
        "Apple.md",
        "notes.TXT",
        "zebra.md",
    ]


def test_list_tree_subfolder_paths_are_relative_posix(vault: Vault) -> None:
    (vault.root / "a" / "b").mkdir(parents=True)
    (vault.root / "a" / "b" / "n.md").write_text("x")
    assert vault.list_tree("a") == [TreeEntry("b", "a/b", True)]
    assert vault.list_tree("a/b") == [TreeEntry("n.md", "a/b/n.md", False)]


def test_list_tree_missing_folder(vault: Vault) -> None:
    with pytest.raises(NotFoundError):
        vault.list_tree("nope")


def test_list_tree_skips_symlink_escaping_vault(vault: Vault, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("s")
    (vault.root / "link").symlink_to(outside)
    (vault.root / "leak.md").symlink_to(outside / "secret.md")
    (vault.root / "ok.md").write_text("x")
    assert names(vault.list_tree()) == ["ok.md"]


def test_walk_notes_skips_hidden_and_non_notes(vault: Vault) -> None:
    for rel in ["a.md", "d/b.txt", "d/e/c.md", "d/pic.png", ".trash/x/old.md", ".paper-pile/n.md"]:
        p = vault.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    assert list(vault.walk_notes()) == ["a.md", "d/b.txt", "d/e/c.md"]


# ---- path safety -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "../x.md",
        "a/../../x.md",
        "/etc/passwd",
        "a\\b.md",
        ".trash/x.md",
        ".paper-pile/n.md",
        "a/.h/x.md",
        "",
    ],
)
def test_unsafe_paths_refused(vault: Vault, bad: str) -> None:
    with pytest.raises(InvalidPathError):
        vault.resolve(bad)
    with pytest.raises(InvalidPathError):
        vault.write_text(bad, "x")


def test_dot_segments_are_normalised(vault: Vault) -> None:
    assert vault.resolve("./a/./b.md") == vault.root / "a" / "b.md"


def test_symlink_escape_refused_for_read_and_write(vault: Vault, tmp_path: Path) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text("top secret")
    (vault.root / "leak.md").symlink_to(secret)
    with pytest.raises(InvalidPathError):
        vault.read_text("leak.md")
    with pytest.raises(InvalidPathError):
        vault.write_text("leak.md", "overwritten")
    assert secret.read_text() == "top secret"


def test_non_note_extension_refused(vault: Vault) -> None:
    with pytest.raises(InvalidPathError):
        vault.write_text("evil.py", "x")
    with pytest.raises(InvalidPathError):
        vault.create_note("evil.sh")


# ---- read / write ----------------------------------------------------------------------


def test_write_read_round_trip_unicode_and_crlf(vault: Vault) -> None:
    text = "# Ünïcode ✓ 日本語\r\nline two\r\n"
    vault.write_text("n.md", text)
    assert vault.read_text("n.md") == text
    assert (vault.root / "n.md").read_bytes() == text.encode("utf-8")


def test_write_replaces_content(vault: Vault) -> None:
    vault.write_text("n.md", "one")
    vault.write_text("n.md", "two")
    assert vault.read_text("n.md") == "two"


def test_write_is_atomic_on_failure(vault: Vault, monkeypatch: pytest.MonkeyPatch) -> None:
    vault.write_text("n.md", "precious")

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("disk exploded")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="exploded"):
        vault.write_text("n.md", "half")
    monkeypatch.undo()
    assert vault.read_text("n.md") == "precious"
    assert [p.name for p in vault.root.iterdir()] == ["n.md"]


def test_write_into_missing_folder_refused(vault: Vault) -> None:
    with pytest.raises(NotFoundError):
        vault.write_text("nofolder/n.md", "x")


def test_read_missing_and_directory(vault: Vault) -> None:
    (vault.root / "dir.md").mkdir()
    with pytest.raises(NotFoundError):
        vault.read_text("missing.md")
    with pytest.raises(NotFoundError):
        vault.read_text("dir.md")


def test_read_invalid_utf8_raises_instead_of_replacing(vault: Vault) -> None:
    (vault.root / "bin.md").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(VaultError, match="UTF-8"):
        vault.read_text("bin.md")


# ---- create ----------------------------------------------------------------------------


def test_create_note_makes_parents_and_never_overwrites(vault: Vault) -> None:
    assert vault.create_note("deep/er/n.md", "hi") == "deep/er/n.md"
    assert vault.read_text("deep/er/n.md") == "hi"
    with pytest.raises(ExistsError):
        vault.create_note("deep/er/n.md", "clobber")
    assert vault.read_text("deep/er/n.md") == "hi"


def test_create_note_under_a_file_refused(vault: Vault) -> None:
    vault.create_note("a.md")
    with pytest.raises(InvalidPathError):
        vault.create_note("a.md/b.md")


def test_create_folder(vault: Vault) -> None:
    assert vault.create_folder("x/y") == "x/y"
    assert (vault.root / "x" / "y").is_dir()
    with pytest.raises(ExistsError):
        vault.create_folder("x/y")


# ---- rename / move ---------------------------------------------------------------------


def test_rename_note_and_move_into_folder(vault: Vault) -> None:
    vault.create_note("a.md", "A")
    vault.create_folder("f")
    assert vault.rename("a.md", "b.md") == "b.md"
    assert vault.rename("b.md", "f/b.md") == "f/b.md"
    assert vault.read_text("f/b.md") == "A"
    assert not (vault.root / "a.md").exists()


def test_rename_folder_moves_contents(vault: Vault) -> None:
    vault.create_note("old/n.md", "N")
    assert vault.rename("old", "new") == "new"
    assert vault.read_text("new/n.md") == "N"


def test_rename_never_overwrites(vault: Vault) -> None:
    vault.create_note("a.md", "A")
    vault.create_note("b.md", "B")
    with pytest.raises(ExistsError):
        vault.rename("a.md", "b.md")
    assert vault.read_text("a.md") == "A" and vault.read_text("b.md") == "B"


def test_rename_refusals(vault: Vault) -> None:
    vault.create_note("a.md")
    vault.create_note("d/x.md")
    with pytest.raises(NotFoundError):
        vault.rename("nope.md", "z.md")
    with pytest.raises(InvalidPathError):
        vault.rename("a.md", "a.png")  # would vanish from the tree
    with pytest.raises(InvalidPathError):
        vault.rename("a.md", ".hidden.md")
    with pytest.raises(InvalidPathError):
        vault.rename("a.md", "../out.md")
    with pytest.raises(NotFoundError):
        vault.rename("a.md", "missing-folder/a.md")
    with pytest.raises(InvalidPathError):
        vault.rename("d", "d/sub")  # folder into itself
    assert vault.read_text("a.md") == "" and vault.read_text("d/x.md") == ""


# ---- delete -> trash -------------------------------------------------------------------


def test_delete_moves_to_trash_keeping_content_and_path(vault: Vault) -> None:
    vault.create_note("notes/a.md", "precious")
    trashed = vault.delete("notes/a.md")
    assert trashed.startswith(".trash/") and trashed.endswith("/notes/a.md")
    assert (vault.root / trashed).read_text() == "precious"
    assert not (vault.root / "notes" / "a.md").exists()
    assert names(vault.list_tree("notes")) == []
    assert list(vault.walk_notes()) == []  # trash is invisible to the app


def test_delete_folder_moves_everything(vault: Vault) -> None:
    vault.create_note("f/a.md", "A")
    vault.create_note("f/sub/b.md", "B")
    trashed = vault.delete("f")
    assert (vault.root / trashed / "a.md").read_text() == "A"
    assert (vault.root / trashed / "sub" / "b.md").read_text() == "B"
    assert not (vault.root / "f").exists()


def test_delete_same_path_twice_keeps_both(vault: Vault) -> None:
    vault.create_note("a.md", "first")
    t1 = vault.delete("a.md")
    vault.create_note("a.md", "second")
    t2 = vault.delete("a.md")
    assert t1 != t2
    assert (vault.root / t1).read_text() == "first"
    assert (vault.root / t2).read_text() == "second"


def test_delete_refusals(vault: Vault) -> None:
    vault.create_note("a.md")
    with pytest.raises(NotFoundError):
        vault.delete("nope.md")
    with pytest.raises(InvalidPathError):
        vault.delete("")  # the vault root
    with pytest.raises(InvalidPathError):
        vault.delete(".trash")
    with pytest.raises(InvalidPathError):
        vault.delete(".paper-pile")
    assert (vault.root / "a.md").exists()


# ---- duplicate -------------------------------------------------------------------------


def test_duplicate_note_names_do_not_collide(vault: Vault) -> None:
    vault.create_note("n.md", "body")
    assert vault.duplicate("n.md") == "n copy.md"
    assert vault.duplicate("n.md") == "n copy 2.md"
    assert vault.duplicate("n copy.md") == "n copy copy.md"
    assert vault.read_text("n copy 2.md") == "body"
    assert vault.read_text("n.md") == "body"


def test_duplicate_folder_copies_tree(vault: Vault) -> None:
    vault.create_note("f/a.md", "A")
    vault.create_note("f/sub/b.md", "B")
    assert vault.duplicate("f") == "f copy"
    assert vault.read_text("f copy/a.md") == "A"
    assert vault.read_text("f copy/sub/b.md") == "B"
    assert vault.read_text("f/a.md") == "A"


def test_duplicate_missing(vault: Vault) -> None:
    with pytest.raises(NotFoundError):
        vault.duplicate("nope.md")


# ---- names and in-folder operations (used by the file tree) ----------------------------


@pytest.mark.parametrize("bad", ["", "   ", ".", "..", ".hidden", "a/b", "a\\b", "x" * 300])
def test_validate_name_rejects(bad: str) -> None:
    with pytest.raises(InvalidPathError):
        validate_name(bad)


def test_validate_name_strips() -> None:
    assert validate_name("  My note  ") == "My note"


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("idea", "idea.md"),
        ("idea.md", "idea.md"),
        ("todo.TXT", "todo.TXT"),
        ("v1.2", "v1.2.md"),
        ("  spaced  ", "spaced.md"),
    ],
)
def test_note_filename(typed: str, expected: str) -> None:
    assert note_filename(typed) == expected


def test_join_rel() -> None:
    assert join_rel("", "a.md") == "a.md"
    assert join_rel(".", "a.md") == "a.md"
    assert join_rel("d", "a.md") == "d/a.md"
    assert join_rel("d/e", "a.md") == "d/e/a.md"


def test_create_in_folder(vault: Vault) -> None:
    vault.create_folder("d")
    assert vault.create_note_in("", "root") == "root.md"
    assert vault.create_note_in("d", "child", "hi") == "d/child.md"
    assert vault.read_text("d/child.md") == "hi"
    assert vault.create_folder_in("d", "sub") == "d/sub"
    with pytest.raises(ExistsError):
        vault.create_note_in("d", "child")
    with pytest.raises(InvalidPathError):
        vault.create_note_in("d", "../escape")
    with pytest.raises(InvalidPathError):
        vault.create_folder_in("", ".trash")


def test_rename_in_place_keeps_extension(vault: Vault) -> None:
    vault.create_note("d/old.md", "x")
    vault.create_note("t.txt", "y")
    assert vault.rename_in_place("d/old.md", "new") == "d/new.md"
    assert vault.rename_in_place("d/new.md", "other.txt") == "d/other.txt"
    assert vault.rename_in_place("t.txt", "renamed") == "renamed.txt"
    assert vault.read_text("d/other.txt") == "x"


def test_rename_in_place_folder_and_noop_and_errors(vault: Vault) -> None:
    vault.create_note("old/n.md", "N")
    vault.create_note("taken.md")
    assert vault.rename_in_place("old", "new") == "new"
    assert vault.read_text("new/n.md") == "N"
    assert vault.rename_in_place("new", "new") == "new"  # same name: nothing happens
    vault.create_note("a.md")
    with pytest.raises(ExistsError):
        vault.rename_in_place("a.md", "taken")
    with pytest.raises(InvalidPathError):
        vault.rename_in_place("a.md", "x/y")
    assert vault.read_text("a.md") == ""


def test_move_into(vault: Vault) -> None:
    vault.create_note("a.md", "A")
    vault.create_folder("f")
    vault.create_note("f/inner/b.md", "B")
    assert vault.move_into("a.md", "f") == "f/a.md"
    assert vault.move_into("f/a.md", "") == "a.md"  # back to the root
    assert vault.move_into("a.md", "") == "a.md"  # already there: no-op
    assert vault.move_into("f/inner", "") == "inner"
    assert vault.read_text("inner/b.md") == "B"


def test_move_into_refusals(vault: Vault) -> None:
    vault.create_note("a.md")
    vault.create_note("f/a.md")
    vault.create_note("d/x.md")
    with pytest.raises(ExistsError):
        vault.move_into("a.md", "f")  # f/a.md exists
    with pytest.raises(InvalidPathError):
        vault.move_into("d", "d")  # into itself
    vault.create_folder("d/sub")
    with pytest.raises(InvalidPathError):
        vault.move_into("d", "d/sub")  # into its own descendant
    with pytest.raises(NotFoundError):
        vault.move_into("a.md", "nope")
    with pytest.raises(NotFoundError):
        vault.move_into("a.md", "f/a.md")  # target is a file, not a folder


# ---- asset_path: images referenced from a note ----------------------------------------


def _png(vault: Vault, rel: str) -> None:
    path = vault.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n")


def test_asset_path_serves_images_from_the_notes_asset_folder(vault: Vault) -> None:
    _png(vault, "notes/.mamba.assets/a3f9c1d2e4b0.png")
    got = vault.asset_path("notes/mamba.md", ".mamba.assets/a3f9c1d2e4b0.png")
    assert got == vault.root / "notes" / ".mamba.assets" / "a3f9c1d2e4b0.png"


def test_asset_path_from_a_root_note_and_with_percent_encoding(vault: Vault) -> None:
    _png(vault, ".my note.assets/pic one.PNG")
    got = vault.asset_path("my note.md", ".my%20note.assets/pic%20one.PNG")
    assert got.name == "pic one.PNG"


def test_asset_path_ordinary_visible_images_and_parent_folders(vault: Vault) -> None:
    _png(vault, "pics/cat.jpg")
    _png(vault, "deep/er/note-pic.webp")
    assert vault.asset_path("deep/er/n.md", "../../pics/cat.jpg").name == "cat.jpg"
    assert vault.asset_path("deep/er/n.md", "note-pic.webp").name == "note-pic.webp"


@pytest.mark.parametrize(
    "ref",
    [
        "../../etc/passwd.png",  # climbs out of the vault
        "../../../x.png",
        "/etc/shadow.png",
        "C:\\x.png",
        "..\\x.png",
        "https://example.org/x.png",
        "data:image/png;base64,AAAA",
        "file:///etc/x.png",
        ".trash/old/pic.png",  # hidden, not an .assets folder
        ".paper-pile/recovery/x.png",
        ".hidden/pic.png",
        ".x.assets/../../.paper-pile/y.png",
        ".assets/pic.png",  # not `.<stem>.assets`
        ".n.assets/.secret.png",  # hidden file
        ".n.assets/notes.md",  # not an image
        ".n.assets/script.js",
        ".n.assets/noext",
        "",
        ".",
        "%2e%2e/%2e%2e/x.png",  # encoded traversal
    ],
)
def test_asset_path_refuses(vault: Vault, ref: str) -> None:
    _png(vault, "n/.n.assets/real.png")
    (vault.root / "n" / ".n.assets" / "script.js").write_text("x")
    (vault.root / "n" / ".n.assets" / "notes.md").write_text("x")
    with pytest.raises(VaultError):
        vault.asset_path("n/n.md", ref)


def test_asset_path_missing_image(vault: Vault) -> None:
    with pytest.raises(NotFoundError):
        vault.asset_path("n.md", ".n.assets/nope.png")


def test_asset_path_refuses_a_bad_note_path(vault: Vault) -> None:
    _png(vault, "x.png")
    for note in ["../n.md", "/abs/n.md", ".trash/n.md", ""]:
        with pytest.raises(InvalidPathError):
            vault.asset_path(note, "x.png")


def test_asset_path_refuses_symlink_escape(vault: Vault, tmp_path: Path) -> None:
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"secret")
    folder = vault.root / ".n.assets"
    folder.mkdir()
    (folder / "leak.png").symlink_to(outside)
    with pytest.raises(InvalidPathError):
        vault.asset_path("n.md", ".n.assets/leak.png")


def test_assets_are_still_invisible_to_every_other_vault_operation(vault: Vault) -> None:
    _png(vault, ".n.assets/a.png")
    with pytest.raises(InvalidPathError):
        vault.resolve(".n.assets/a.png")
    assert vault.list_tree() == []


@pytest.mark.parametrize(
    ("name", "plain"),
    [
        ("todo.txt", True),
        ("TODO.TXT", True),
        ("a.b.txt", True),
        ("note.md", False),
        ("n.MD", False),
        ("txt", False),
        ("x.txt.md", False),
    ],
)
def test_is_plain_text(name: str, plain: bool) -> None:
    assert is_plain_text(name) is plain


def test_folders_lists_visible_folders_only(tmp_path) -> None:
    from paper_pile.core.vault import Vault

    for rel in ("a", "a/b", "Zed", ".hidden", ".paper-pile/x", "a/.trash"):
        (tmp_path / rel).mkdir(parents=True)
    (tmp_path / "note.md").write_text("x")
    assert Vault(tmp_path).folders() == ["a", "a/b", "Zed"]


def test_recent_notes_are_newest_first_and_capped(vault: Vault) -> None:
    for i, name in enumerate(["a.md", "sub/b.md", "c.txt"]):
        path = vault.create_note(name) if "/" not in name else None
        if path is None:
            vault.create_folder("sub")
            path = vault.create_note(name)
        os.utime(vault.resolve(path), (1000 + i, 1000 + i))
    assert vault.recent_notes() == ["c.txt", "sub/b.md", "a.md"]
    assert vault.recent_notes(limit=2) == ["c.txt", "sub/b.md"]


def test_free_numbered_name_starts_at_one_and_skips_taken(vault: Vault) -> None:
    assert vault.free_numbered_name("", "Untitled", ".md") == "Untitled 1"
    vault.create_note("Untitled 1.md")
    vault.create_note("Untitled 2.md")
    assert vault.free_numbered_name("", "Untitled", ".md") == "Untitled 3"
    vault.create_folder("d")
    assert vault.free_numbered_name("d", "Untitled", ".md") == "Untitled 1"
