from pathlib import Path

import pytest

from paper_pile.core.vault import META_DIR, VaultError, ensure_vault_dir, resolve_vault_path


def test_resolve_existing_dir(tmp_path: Path) -> None:
    assert resolve_vault_path(tmp_path) == tmp_path.resolve()
    assert resolve_vault_path(str(tmp_path)) == tmp_path.resolve()


def test_resolve_relative_dot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert resolve_vault_path(".") == tmp_path.resolve()


def test_resolve_expands_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "notes").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    assert resolve_vault_path("~/notes") == (tmp_path / "notes").resolve()


def test_resolve_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(VaultError, match="does not exist"):
        resolve_vault_path(tmp_path / "nope")


def test_resolve_file_raises(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text("x")
    with pytest.raises(VaultError, match="not a directory"):
        resolve_vault_path(f)


def test_ensure_vault_dir_creates_and_is_idempotent(tmp_path: Path) -> None:
    meta = ensure_vault_dir(tmp_path)
    assert meta == tmp_path / META_DIR and meta.is_dir()
    (meta / "keep.txt").write_text("x")
    ensure_vault_dir(tmp_path)
    assert (meta / "keep.txt").read_text() == "x"
