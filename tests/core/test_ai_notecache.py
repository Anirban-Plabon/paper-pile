import os
from pathlib import Path

import pytest

from paper_pile.core.ai.notecache import PATHS_TTL_S, NoteCache
from paper_pile.core.vault import Vault


def test_paths_are_kept_for_a_while_or_until_invalidated(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.create_note("a.md", "a")
    now = [0.0]
    cache = NoteCache(v, clock=lambda: now[0])
    assert cache.paths() == ["a.md"]
    v.create_note("b.md", "b")
    assert cache.paths() == ["a.md"]
    now[0] += PATHS_TTL_S + 1
    assert sorted(cache.paths()) == ["a.md", "b.md"]
    v.create_note("c.md", "c")
    cache.invalidate()
    assert sorted(cache.paths()) == ["a.md", "b.md", "c.md"]


def test_text_is_read_again_only_when_the_file_changes(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.create_note("a.md", "one")
    cache = NoteCache(v)
    assert cache.read("a.md") == "one"
    path = v.resolve("a.md")
    path.write_text("two!")  # another size
    assert cache.read("a.md") == "two!"
    st = path.stat()
    path.write_text("tri!")  # same size: the modification time tells
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert cache.read("a.md") == "tri!"
    path.unlink()
    assert cache.read("a.md") is None and cache.read("../x.md") is None


def test_only_the_last_read_texts_are_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import paper_pile.core.ai.notecache as notecache

    monkeypatch.setattr(notecache, "MAX_TEXTS", 3)
    v = Vault(tmp_path / "v")
    v.root.mkdir()
    for n in range(5):
        v.create_note(f"{n}.md", f"text {n}")
    cache = notecache.NoteCache(v)
    for n in (0, 1, 2, 0, 3, 4):
        assert cache.read(f"{n}.md") == f"text {n}"
    assert list(cache._texts) == ["0.md", "3.md", "4.md"]  # 0 was read again, so it stayed
