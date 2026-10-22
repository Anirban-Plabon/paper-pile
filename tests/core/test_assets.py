import struct
from pathlib import Path

import pytest

from paper_pile.core import assets
from paper_pile.core.assets import (
    ImageError,
    assets_folder,
    assets_prefix,
    image_markdown,
    image_size,
    plan_ref_edits,
    referenced_files,
    save_image,
    set_width_edit,
    sniff_image,
    sweep_orphans,
)
from paper_pile.core.rewrite import apply_edits, plan_rewrites
from paper_pile.core.vault import Vault


def png(w: int = 10, h: int = 20, pad: bytes = b"") -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + pad


def jpeg(w: int = 300, h: int = 200) -> bytes:
    sof = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, h, w) + b"\x03" + b"\x00" * 9
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9 + sof


def gif(w: int = 7, h: int = 9) -> bytes:
    return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00" * 8


def webp_x(w: int = 800, h: int = 600) -> bytes:
    body = b"WEBP" + b"VP8X" + struct.pack("<I", 10) + b"\x00" * 4
    body += (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", len(body)) + body


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.create_note("a.md", "# A\n")
    v.create_folder("sub")
    v.create_note("sub/mamba.md", "# Mamba\n")
    return v


# ---- recognising and measuring -----------------------------------------------------------------


def test_sniff_by_content() -> None:
    assert sniff_image(png()) == "png" and sniff_image(jpeg()) == "jpg"
    assert sniff_image(gif()) == "gif" and sniff_image(webp_x()) == "webp"
    assert sniff_image(b"BM" + b"\x00" * 30) == "bmp"
    assert sniff_image(b"\x00\x00\x00\x1cftypavif" + b"\x00" * 20) == "avif"
    assert sniff_image(SVG) == "svg" and sniff_image(b"\xef\xbb\xbf  \n" + SVG) == "svg"
    for junk in [b"", b"hello", b"<html><svgx>", b"%PDF-1.4", b"MZ\x90\x00", b"PK\x03\x04"]:
        assert sniff_image(junk) is None


def test_image_size() -> None:
    assert image_size(png(10, 20)) == (10, 20)
    assert image_size(jpeg(300, 200)) == (300, 200)
    assert image_size(gif(7, 9)) == (7, 9)
    assert image_size(webp_x(800, 600)) == (800, 600)
    assert image_size(SVG) is None and image_size(b"junk") is None
    assert image_size(png()[:12]) is None  # truncated: no crash


# ---- names, saving ---------------------------------------------------------------------------


def test_folder_and_prefix_names() -> None:
    assert assets_prefix("mamba.md") == ".mamba.assets"
    assert assets_folder("mamba.md") == ".mamba.assets"
    assert assets_folder("notes/sub/mamba.md") == "notes/sub/.mamba.assets"
    assert assets_folder("a.b.txt") == ".a.b.assets"


def test_save_image_names_it_by_hash(vault: Vault) -> None:
    data = png(1000, 500, b"x")
    saved = save_image(vault, "sub/mamba.md", data)
    assert saved.name.endswith(".png") and len(saved.name) == 12 + 4
    assert saved.path == f"sub/.mamba.assets/{saved.name}" and saved.new
    assert saved.ref == f".mamba.assets/{saved.name}"
    assert (vault.root / saved.path).read_bytes() == data
    assert saved.width == 640  # capped
    small = save_image(vault, "a.md", png(50, 50, b"y"))
    assert small.width == 50


def test_same_picture_is_stored_once(vault: Vault) -> None:
    first = save_image(vault, "a.md", png(5, 5))
    second = save_image(vault, "a.md", png(5, 5))
    assert first.name == second.name and first.new and not second.new
    assert len(list((vault.root / ".a.assets").iterdir())) == 1


def test_save_refuses_non_images_and_big_files(
    vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ImageError):
        save_image(vault, "a.md", b"MZ not an image")
    with pytest.raises(ImageError):
        save_image(vault, "a.md", b"")
    monkeypatch.setattr(assets, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(ImageError):
        save_image(vault, "a.md", png(1, 1, b"x" * 50))
    assert not (vault.root / ".a.assets").exists()  # nothing half-written


def test_save_refuses_bad_note_paths(vault: Vault) -> None:
    for bad in ["../x.md", "/abs.md", ".trash/x.md", "a.exe"]:
        with pytest.raises(Exception):  # noqa: B017  (InvalidPathError)
            save_image(vault, bad, png())


def test_reference_text() -> None:
    assert image_markdown(".a.assets/x.png", 480) == "![image|480](.a.assets/x.png)"
    assert image_markdown(".a.assets/x.png") == "![image](.a.assets/x.png)"


def test_note_names_with_spaces_and_unicode_make_valid_references(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.create_note("my note é.md")
    saved = save_image(v, "my note é.md", png(30, 30))
    assert " " not in saved.ref
    md = image_markdown(saved.ref, saved.width)
    assert v.asset_path("my note é.md", saved.ref).is_file()  # the route can serve it
    assert referenced_files(md, "my note é.md") == {saved.name}


# ---- what a note refers to / sweeping ------------------------------------------------------


def test_referenced_files() -> None:
    text = (
        "![a](.mamba.assets/one.png) and ![b|300](./.mamba.assets/two.png) and "
        "![c](.other.assets/three.png) ![d](https://e.org/x.png) `![e](.mamba.assets/code.png)`\n\n"
        "```\n![f](.mamba.assets/fence.png)\n```\n\n![g][r]\n\n[r]: .mamba.assets/ref.png\n"
    )
    assert referenced_files(text, "mamba.md") == {"one.png", "two.png", "ref.png"}


def test_sweep_moves_unreferenced_images_to_trash(vault: Vault) -> None:
    keep = save_image(vault, "a.md", png(1, 1, b"k"))
    gone = save_image(vault, "a.md", png(2, 2, b"g"))
    text = f"![x]({keep.ref})"
    trashed = sweep_orphans(vault, "a.md", text)
    assert len(trashed) == 1 and trashed[0].startswith(".trash/") and trashed[0].endswith(gone.name)
    assert (vault.root / keep.path).exists() and not (vault.root / gone.path).exists()
    assert (vault.root / trashed[0]).read_bytes() == png(2, 2, b"g")  # recoverable, not deleted


def test_sweep_removes_the_empty_folder(vault: Vault) -> None:
    saved = save_image(vault, "a.md", png(1, 1))
    sweep_orphans(vault, "a.md", "no images any more")
    assert not (vault.root / ".a.assets").exists()
    assert any(vault.root.glob(f".trash/*/.a.assets/{saved.name}"))
    assert sweep_orphans(vault, "a.md", "") == []  # nothing left: no error


def test_sweep_leaves_foreign_files_and_other_notes_alone(vault: Vault) -> None:
    save_image(vault, "sub/mamba.md", png(3, 3))
    (vault.root / ".a.assets").mkdir()
    (vault.root / ".a.assets" / "notes.txt").write_text("not an image")
    sweep_orphans(vault, "a.md", "")
    assert (vault.root / ".a.assets" / "notes.txt").exists()  # not ours to move
    assert len(list((vault.root / "sub" / ".mamba.assets").iterdir())) == 1


# ---- lifecycle through Vault ops -----------------------------------------------------------


def test_rename_moves_the_assets_folder(vault: Vault) -> None:
    saved = save_image(vault, "a.md", png(4, 4))
    vault.rename("a.md", "b.md")
    assert not (vault.root / ".a.assets").exists()
    assert (vault.root / ".b.assets" / saved.name).is_file()


def test_move_to_another_folder_takes_images_along(vault: Vault) -> None:
    saved = save_image(vault, "a.md", png(4, 4))
    vault.move_into("a.md", "sub")
    assert (vault.root / "sub" / ".a.assets" / saved.name).is_file()
    assert not (vault.root / ".a.assets").exists()


def test_rename_merges_into_an_existing_assets_folder(vault: Vault) -> None:
    one = save_image(vault, "a.md", png(4, 4, b"1"))
    (vault.root / ".b.assets").mkdir()
    (vault.root / ".b.assets" / "old.png").write_bytes(png())
    vault.rename("a.md", "b.md")
    assert (vault.root / ".b.assets" / one.name).is_file() and (
        vault.root / ".b.assets" / "old.png"
    ).is_file()


def test_folder_rename_keeps_images_with_their_notes(vault: Vault) -> None:
    saved = save_image(vault, "sub/mamba.md", png(4, 4))
    vault.rename("sub", "renamed")
    assert (vault.root / "renamed" / ".mamba.assets" / saved.name).is_file()


def test_delete_trashes_the_images_with_the_note(vault: Vault) -> None:
    saved = save_image(vault, "a.md", png(4, 4))
    trashed = vault.delete("a.md")
    stamp_dir = vault.root / Path(trashed).parent
    assert (stamp_dir / ".a.assets" / saved.name).read_bytes() == png(4, 4)
    assert not (vault.root / ".a.assets").exists()


def test_duplicate_copies_images_and_rewrites_the_copy(vault: Vault) -> None:
    saved = save_image(vault, "a.md", png(4, 4))
    vault.write_text("a.md", f"![image|40]({saved.ref}) and ![x]({saved.ref})\n")
    copy = vault.duplicate("a.md")
    assert copy == "a copy.md"
    assert (vault.root / ".a copy.assets" / saved.name).is_file()  # its own copy
    assert (vault.root / ".a.assets" / saved.name).is_file()  # the original is untouched
    text = vault.read_text(copy)
    assert text == (
        f"![image|40](.a%20copy.assets/{saved.name}) and ![x](.a%20copy.assets/{saved.name})\n"
    )
    assert vault.asset_path(copy, f".a%20copy.assets/{saved.name}").is_file()
    assert vault.read_text("a.md").count(".a.assets/") == 2


def test_notes_without_images_are_unaffected(vault: Vault) -> None:
    vault.rename("a.md", "b.md")
    assert vault.duplicate("b.md") == "b copy.md"
    vault.delete("b.md")
    assert not list(vault.root.glob(".*.assets"))


# ---- rewriting references after a rename ---------------------------------------------------


def test_plan_ref_edits_changes_only_the_folder_part() -> None:
    text = (
        '![image|40](.a.assets/x.png) ![y](./.a.assets/y.png "t") '
        "![o](.other.assets/z.png) [l](.a.assets/doc.png)"
    )
    out = apply_edits(text, plan_ref_edits(text, "a.md", "b.md"))
    assert out == (
        '![image|40](.b.assets/x.png) ![y](./.b.assets/y.png "t") ![o](.other.assets/z.png) '
        "[l](.a.assets/doc.png)"
    )
    assert plan_ref_edits(text, "a.md", "sub/a.md") == []  # same stem: same folder name


def test_plan_ref_edits_handles_encoded_and_angle_forms() -> None:
    text = "![a](.my%20note.assets/x.png) ![b](<.my note.assets/y.png>)"
    out = apply_edits(text, plan_ref_edits(text, "my note.md", "new name.md"))
    assert out == "![a](.new%20name.assets/x.png) ![b](<.new name.assets/y.png>)"


def test_plan_ref_edits_ignores_code_and_non_images() -> None:
    text = "`![a](.a.assets/x.png)`\n\n```\n![b](.a.assets/y.png)\n```\n"
    assert plan_ref_edits(text, "a.md", "b.md") == []


def test_rename_rewrite_pipeline_end_to_end(vault: Vault) -> None:
    saved = save_image(vault, "a.md", png(4, 4))
    vault.write_text("a.md", f"![image|40]({saved.ref})\n[[b]]\n")
    vault.create_note("link.md", "see [[a]] and ![i](.a.assets/elsewhere.png)\n")
    moves = {"a.md": "b.md"}
    vault.rename("a.md", "b.md")
    paths = set(vault.walk_notes())
    texts = {p: vault.read_text(p) for p in paths}
    plan = plan_rewrites(moves, paths, texts)
    assert plan.texts["b.md"].startswith(f"![image|40](.b.assets/{saved.name})")
    assert vault.asset_path("b.md", f".b.assets/{saved.name}").is_file()
    assert "link.md" in plan.texts and "[[b]]" in plan.texts["link.md"]
    assert (
        ".a.assets/elsewhere.png" in plan.texts["link.md"]
    )  # another note's own folder: untouched


# ---- resizing ------------------------------------------------------------------------------


def test_set_width_replaces_or_adds_only_the_number() -> None:
    text = "intro ![image|300](.a.assets/x.png) outro"
    start = text.index("![")
    edit = set_width_edit(text, start, 450)
    assert edit and apply_edits(text, [edit]) == "intro ![image|450](.a.assets/x.png) outro"
    plain = "![photo](.a.assets/x.png)"
    edit = set_width_edit(plain, 0, 200)
    assert edit and apply_edits(plain, [edit]) == "![photo|200](.a.assets/x.png)"
    spaced = "![alt | 12](x.png)"
    edit = set_width_edit(spaced, 0, 99)
    assert edit and apply_edits(spaced, [edit]) == "![alt |99](x.png)"
    nested = "![a [b] c|10](x.png)"
    edit = set_width_edit(nested, 0, 111)
    assert edit and apply_edits(nested, [edit]) == "![a [b] c|111](x.png)"
    empty = "![](x.png)"
    edit = set_width_edit(empty, 0, 100)
    assert edit and apply_edits(empty, [edit]) == "![|100](x.png)"


def test_set_width_clamps_and_rejects() -> None:
    edit = set_width_edit("![a](x.png)", 0, 5)
    assert edit and edit.insert == "|20"
    edit = set_width_edit("![a](x.png)", 0, 99999)
    assert edit and edit.insert == "|4000"
    assert set_width_edit("hello", 0, 100) is None
    assert set_width_edit("[a](x.png)", 0, 100) is None
    assert set_width_edit("![a\nb](x.png)", 0, 100) is None
    assert set_width_edit("![a] (x.png)", 0, 100) is None
    assert set_width_edit("![a](x.png)", 99, 100) is None


# ---- the shared images folder (P13.6) ---------------------------------------------------------


def test_new_images_go_to_the_images_folder(tmp_path: Path) -> None:
    from paper_pile.core.assets import save_image

    vault = Vault(tmp_path)
    (tmp_path / "notes" / "deep").mkdir(parents=True)
    top = save_image(vault, "a.md", png(), ".image")
    deep = save_image(vault, "notes/deep/b.md", png(), ".image")
    assert top.path == f".image/{top.name}" and top.ref == f".image/{top.name}"
    assert deep.ref == f"../../.image/{deep.name}" and not deep.new  # same picture: one file
    assert vault.asset_path("notes/deep/b.md", deep.ref).read_bytes() == png()
    assert not (tmp_path / ".a.assets").exists()
    spaced = save_image(vault, "a.md", png(), "My pictures")
    assert spaced.ref == f"My%20pictures/{spaced.name}"


def test_moving_a_note_repoints_its_shared_images() -> None:
    from paper_pile.core.assets import plan_media_edits
    from paper_pile.core.rewrite import apply_edits

    text = (
        "![a|300](.image/x.png) ![b](<.image/y z.png>) ![own](.a.assets/o.png) "
        "![web](https://e.com/.image/w.png) ![other](pics/p.png)"
    )
    moved = apply_edits(text, plan_media_edits(text, "a.md", "notes/deep/a.md", ".image"))
    assert moved == (
        "![a|300](../../.image/x.png) ![b](<../../.image/y%20z.png>) ![own](.a.assets/o.png) "
        "![web](https://e.com/.image/w.png) ![other](pics/p.png)"
    )
    back = apply_edits(moved, plan_media_edits(moved, "notes/deep/a.md", "a.md", ".image"))
    assert back.replace("y%20z", "y z") == text
    assert plan_media_edits(text, "a.md", "b.md", ".image") == []  # same folder: nothing
    assert plan_media_edits(text, "a.md", "n/a.md", "") == []
