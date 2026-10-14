import os
import stat
from pathlib import Path

import pytest

from paper_pile.core.fsutil import atomic_write_bytes


def test_writes_new_file_with_default_mode(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    atomic_write_bytes(f, b"hello")
    assert f.read_bytes() == b"hello"
    assert stat.S_IMODE(f.stat().st_mode) == 0o644


def test_replaces_and_keeps_existing_mode(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_bytes(b"old")
    f.chmod(0o600)
    atomic_write_bytes(f, b"new")
    assert f.read_bytes() == b"new"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_failure_keeps_original_and_leaves_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "a.txt"
    f.write_bytes(b"precious")

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("disk exploded")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="exploded"):
        atomic_write_bytes(f, b"half-written")
    assert f.read_bytes() == b"precious"
    assert [p.name for p in tmp_path.iterdir()] == ["a.txt"]
