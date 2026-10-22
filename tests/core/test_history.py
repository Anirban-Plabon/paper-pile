"""Version history: reverse diffs, keyframes, thinning, the cap, renames (PLAN §4.18)."""

import sqlite3
import zlib
from pathlib import Path

import pytest

from paper_pile.core.history import (
    DAY,
    KEYFRAME,
    DamagedVersion,
    History,
    Sessions,
    apply_diff,
    kept_versions,
    make_diff,
)


class Clock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def lines(n: int, tag: str = "") -> str:
    return "".join(f"line {i}{tag}\n" for i in range(n))


@pytest.mark.parametrize(
    "newer,older",
    [("", ""), ("a\nb\n", "a\nb\n"), ("a\nb", "a\nc\nb"), ("x\n", ""), ("", "y"), (lines(50), "")],
)
def test_diff_turns_the_newer_text_back_into_the_older(newer: str, older: str) -> None:
    assert apply_diff(newer, make_diff(newer, older)) == older


def test_a_diff_that_does_not_fit_is_damage_not_wrong_text() -> None:
    with pytest.raises(DamagedVersion):
        apply_diff("one line\n", make_diff(lines(5), lines(4)))
    with pytest.raises(DamagedVersion):
        apply_diff("x", b"not zlib")


def test_versions_round_trip_and_store_diffs(tmp_path: Path) -> None:
    clock = Clock()
    h = History(tmp_path, clock=clock)
    base = lines(300).splitlines(keepends=True)
    texts = []
    for v in range(6):  # each version edits a couple of lines, like real editing
        base[v * 40] = f"edited in version {v}\n"
        texts.append("".join(base) + ("" if v % 2 else f"end {v}\n"))
    for text in texts:
        clock.now += 60
        assert h.record("n.md", text, "edit")
    assert not h.record("n.md", texts[-1], "edit")  # same as the newest: not stored again
    found = h.versions("n.md")
    assert len(found) == 6
    assert [h.text("n.md", v.id) for v in found] == list(reversed(texts))
    # only the newest is whole; the others are much smaller than copies
    sizes = (
        sqlite3.connect(h.db_path)
        .execute("SELECT whole, length(data) FROM versions ORDER BY ts")
        .fetchall()
    )
    assert [w for w, _ in sizes] == [0, 0, 0, 0, 0, 1]
    assert h.size() < 3 * len(zlib.compress(texts[0].encode()))


def test_a_whole_copy_every_keyframe_versions(tmp_path: Path) -> None:
    clock = Clock()
    h = History(tmp_path, clock=clock)
    for v in range(KEYFRAME + 3):
        clock.now += 1
        h.record("n.md", f"version {v}\n", "edit")
    whole = [
        w
        for (w,) in sqlite3.connect(h.db_path).execute(
            "SELECT whole FROM versions ORDER BY ts DESC"
        )
    ]
    assert whole[0] == 1 and 1 in whole[1:] and whole.count(0) <= KEYFRAME - 1 + 3
    assert all(
        h.text("n.md", v.id) == f"version {KEYFRAME + 2 - i}\n"
        for i, v in enumerate(h.versions("n.md"))
    )


def test_a_damaged_diff_spoils_only_older_versions(tmp_path: Path) -> None:
    clock = Clock()
    h = History(tmp_path, clock=clock)
    for v in range(4):
        clock.now += 1
        h.record("n.md", f"v{v}\n", "edit")
    newest, second, third, oldest = h.versions("n.md")
    db = sqlite3.connect(h.db_path)
    db.execute("UPDATE versions SET data=? WHERE id=?", (make_diff("v3\n", "WRONG\n"), second.id))
    db.commit()
    assert h.text("n.md", newest.id) == "v3\n"
    for v in (second, third, oldest):
        with pytest.raises(DamagedVersion):
            h.text("n.md", v.id)


def test_thinning_keeps_today_then_one_per_day_week_month() -> None:
    now = 1_800_000_000.0
    stamps = [now - 60 * m for m in (1, 5, 30)]  # today: all kept
    stamps += [now - 2 * DAY - h * 3600 for h in (0, 1, 2)]  # one day 2 days ago: 1 kept
    stamps += [now - 10 * DAY - d * 3600 for d in (0, 1)]  # same week: 1 kept
    stamps += [now - 200 * DAY, now - 201 * DAY]  # same month (probably): at most 2
    kept = kept_versions(stamps, now)
    assert {0, 1, 2, 3, 6} <= kept
    assert 4 not in kept and 5 not in kept and 7 not in kept
    assert kept_versions([now - 400 * DAY], now) == {0}  # the newest is always kept


def test_thinning_rewrites_a_chain_that_still_rebuilds(tmp_path: Path) -> None:
    clock = Clock()
    h = History(tmp_path, clock=clock)
    for v in range(5):
        h.record("n.md", f"{v}\n" + lines(20), "edit")
        clock.now += 3600  # an hour apart
    clock.now += 3 * DAY  # three days later: those five are on one day -> one is kept
    h.record("n.md", "fresh\n", "edit")
    found = h.versions("n.md")
    assert len(found) == 2
    assert [h.text("n.md", v.id) for v in found] == ["fresh\n", "4\n" + lines(20)]


def test_the_cap_drops_the_oldest_but_never_a_newest(tmp_path: Path) -> None:
    clock = Clock()
    h = History(tmp_path, clock=clock, cap_bytes=2000)
    import random

    rnd = random.Random(1)
    for v in range(6):
        clock.now += 60
        for note in ("a.md", "b.md"):
            noise = "".join(rnd.choice("abcdefghij") for _ in range(800))
            h.record(note, f"{note} {v}\n{noise}\n", "edit")
    assert h.size() <= 2000
    for note in ("a.md", "b.md"):
        newest = h.versions(note)[0]
        assert h.text(note, newest.id).startswith(f"{note} 5\n")


def test_history_follows_renames_of_notes_and_folders(tmp_path: Path) -> None:
    h = History(tmp_path)
    h.record("dir/a.md", "a", "edit")
    h.record("dir/ab.md", "ab", "edit")
    h.record("dirx/c.md", "c", "edit")
    h.renamed("dir", "new")
    assert h.versions("dir/a.md") == []
    assert h.text("new/a.md", h.versions("new/a.md")[0].id) == "a"
    assert h.versions("new/ab.md") and h.versions("dirx/c.md")  # dirx is not dir/
    h.renamed("new/a.md", "z.md")
    assert h.versions("z.md")


def test_sessions_start_on_the_first_save_and_after_a_long_pause() -> None:
    clock = Clock()
    s = Sessions(gap=1800, clock=clock)
    assert s.starts("a.md")
    clock.now += 600
    assert not s.starts("a.md")
    clock.now += 1801
    assert s.starts("a.md")
    s.renamed("a.md", "b.md")
    clock.now += 10
    assert not s.starts("b.md")


def test_all_texts_lists_every_version_newest_first(tmp_path: Path) -> None:
    clock = Clock()
    h = History(tmp_path, clock=clock)
    for v in range(3):
        clock.now += 1
        h.record("n.md", f"v{v}\n", f"reason {v}")
    assert [(v.reason, t) for v, t in h.all_texts("n.md")] == [
        ("reason 2", "v2\n"),
        ("reason 1", "v1\n"),
        ("reason 0", "v0\n"),
    ]
    assert h.all_texts("other.md") == []
