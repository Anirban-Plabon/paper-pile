from pathlib import Path

import pytest

from paper_pile.core.profile import (
    MAX_AVATAR_BYTES,
    AvatarError,
    avatar_path,
    initials,
    remove_avatar,
    save_avatar,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 30
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 30
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"


def test_initials() -> None:
    assert initials("Ada Lovelace") == "AL" and initials("ada") == "AD" and initials("") == "?"
    assert initials("  jean-luc  picard ") == "JP" and initials("x") == "X"


def test_save_replace_and_remove(tmp_path: Path) -> None:
    assert save_avatar(PNG, tmp_path) == "avatar.png"
    assert avatar_path("avatar.png", tmp_path) is not None
    assert save_avatar(JPG, tmp_path) == "avatar.jpg"  # the old picture goes
    assert avatar_path("avatar.png", tmp_path) is None
    assert (tmp_path / "avatar.jpg").read_bytes() == JPG
    remove_avatar(tmp_path)
    assert list(tmp_path.glob("avatar.*")) == []
    remove_avatar(tmp_path)  # nothing left: harmless


@pytest.mark.parametrize("data", [SVG, b"hello", b"", b"MZ\x90\x00"])
def test_only_pictures_are_accepted(tmp_path: Path, data: bytes) -> None:
    with pytest.raises(AvatarError):
        save_avatar(data, tmp_path)
    assert list(tmp_path.glob("avatar.*")) == []


def test_too_big_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AvatarError):
        save_avatar(PNG + b"x" * MAX_AVATAR_BYTES, tmp_path)


def test_avatar_path_only_serves_the_avatar_file(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("secret")
    (tmp_path / "avatar.png").write_bytes(PNG)
    for bad in ["config.toml", "../config.toml", "avatar.svg", "avatar.png/../config.toml", ""]:
        assert avatar_path(bad, tmp_path) is None, bad
    assert avatar_path("avatar.png", tmp_path) == tmp_path / "avatar.png"
