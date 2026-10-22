import os
import struct
from datetime import date, datetime
from pathlib import Path

from paper_pile.core.gallery import group_by_day, image_users, list_images, trash_image
from paper_pile.core.vault import Vault


def png(w: int = 10, h: int = 20) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h)


def _at(path: Path, day: str) -> None:
    ts = datetime.fromisoformat(f"{day}T12:00:00").timestamp()
    os.utime(path, (ts, ts))


def _vault(tmp_path: Path) -> Vault:
    for rel, data in {
        ".image/new.png": png(30, 40),
        ".image/old.png": png(),
        "notes/.a.assets/own.png": png(),
        ".trash/x/gone.png": png(),
        ".paper-pile/p.png": png(),
        "notes/pics/loose.png": png(),  # neither the images folder nor an assets folder
    }.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    _at(tmp_path / ".image/new.png", "2026-10-20")
    _at(tmp_path / ".image/old.png", "2026-10-01")
    _at(tmp_path / "notes/.a.assets/own.png", "2026-10-20")
    (tmp_path / "notes" / "a.md").write_text(
        "![](.a.assets/own.png) ![x|200](../.image/new.png) ![w](https://e.com/z.png)"
    )
    (tmp_path / "b.md").write_text("![](.image/new.png)")
    return Vault(tmp_path)


def test_list_images(tmp_path: Path) -> None:
    images = list_images(_vault(tmp_path), ".image")
    paths = [i.path for i in images]
    assert paths == [".image/new.png", "notes/.a.assets/own.png", ".image/old.png"]
    new = images[0]
    assert (new.width, new.height, new.name, new.day) == (30, 40, "new.png", date(2026, 10, 20))
    assert new.used_by == ["b.md", "notes/a.md"]
    assert images[2].used_by == []  # unused


def test_users_ignore_urls_and_escapes(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (tmp_path / "c.md").write_text("![](../outside.png) ![](/abs.png)")
    users = image_users(vault, ["c.md", "notes/a.md"])
    assert set(users) == {"notes/.a.assets/own.png", ".image/new.png"}


def test_group_by_day(tmp_path: Path) -> None:
    images = list_images(_vault(tmp_path), ".image")
    days = group_by_day(images)
    assert [d for d, _ in days] == [date(2026, 10, 20), date(2026, 10, 1)]
    assert len(days[0][1]) == 2
    assert [d for d, _ in group_by_day(images, newest_first=False)][0] == date(2026, 10, 1)


def test_trash_image(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    moved = trash_image(vault, ".image/old.png")
    assert moved.startswith(".trash/") and moved.endswith(".image/old.png")
    assert not (tmp_path / ".image/old.png").exists()
