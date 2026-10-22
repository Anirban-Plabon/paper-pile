"""Earlier versions of notes (PLAN §4.18), in ``<vault>/.paper-pile/history.db``. No UI here.

Diffs, not copies: per note, the newest recorded version is stored whole and every older one as
a *reverse* line diff — how to turn the next newer version back into it — so text that stays the
same is stored once. Every ``KEYFRAME``-th version is stored whole too, which bounds how far a
rebuild walks and how much one damaged diff can take with it. Each version keeps the SHA-256 of
its text; a rebuilt text that does not match raises :class:`DamagedVersion` (never wrong text).

A diff is a JSON list of ops over the newer text's lines (``keepends``): ``n`` keeps ``n`` lines,
``[n, [lines…]]`` drops ``n`` lines and puts ``lines`` in their place; zlib-compressed.

Old versions are thinned (:func:`kept_versions`): everything from the last day, then the newest
per day for a week, per week for a month, per month after that. When the whole history passes
``cap_bytes`` the oldest versions go first. Dropping versions rebuilds the note's chain.

Unlike ``index.db`` this cannot be rebuilt from the vault, so it is a separate file; it is never
needed to read the notes themselves.
"""

import difflib
import hashlib
import json
import logging
import sqlite3
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from paper_pile.core.vault import META_DIR

log = logging.getLogger("paper_pile.history")

KEYFRAME = 25  # a whole copy every this many versions of a note
CAP_BYTES = 50 * 1024 * 1024
SESSION_GAP_S = 30 * 60  # a save after this long without one starts a new editing session
DAY = 24 * 3600
_SCHEMA = """
CREATE TABLE IF NOT EXISTS versions(
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    ts REAL NOT NULL,
    reason TEXT NOT NULL,
    sha TEXT NOT NULL,
    whole INTEGER NOT NULL,  -- 1: data is the text; 0: a diff from the next newer version
    data BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS versions_path ON versions(path, ts);
"""


class DamagedVersion(Exception):
    """A version could not be rebuilt exactly (a damaged diff or database)."""


@dataclass(frozen=True, slots=True)
class Version:
    id: int
    ts: float
    reason: str  # "edit", "before AI", "before merge", ...


@dataclass(frozen=True, slots=True)
class _Row:
    id: int
    ts: float
    reason: str
    sha: str
    whole: bool
    data: bytes


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- diffs ---------------------------------------------------------------------------------


def make_diff(newer: str, older: str) -> bytes:
    """The ops that turn ``newer`` into ``older``, compressed."""
    a, b = newer.splitlines(keepends=True), older.splitlines(keepends=True)
    ops: list[Any] = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            ops.append(i2 - i1)
        else:
            ops.append([i2 - i1, b[j1:j2]])
    return zlib.compress(json.dumps(ops, separators=(",", ":")).encode("utf-8"))


def apply_diff(newer: str, data: bytes) -> str:
    """``newer`` turned back into the older text ``data`` describes."""
    try:
        ops = json.loads(zlib.decompress(data))
    except (zlib.error, ValueError) as exc:
        raise DamagedVersion("unreadable diff") from exc
    lines = newer.splitlines(keepends=True)
    out: list[str] = []
    pos = 0
    for op in ops:
        if isinstance(op, int):
            out.extend(lines[pos : pos + op])
            pos += op
        elif isinstance(op, list) and len(op) == 2 and isinstance(op[0], int):
            out.extend(str(x) for x in op[1])
            pos += op[0]
        else:
            raise DamagedVersion("unknown diff op")
    if pos != len(lines):
        raise DamagedVersion("diff does not fit the newer text")
    return "".join(out)


# ---- thinning ------------------------------------------------------------------------------


def kept_versions(stamps: list[float], now: float) -> set[int]:
    """Which of ``stamps`` (seconds) to keep, as indexes: the newest always; everything from the
    last day; then the newest per day for 7 days, per ISO week for 30 days, per month after."""
    order = sorted(range(len(stamps)), key=lambda i: stamps[i], reverse=True)
    keep: set[int] = set(order[:1])
    seen: set[tuple[str, Any]] = set()
    for i in order:
        age = now - stamps[i]
        if age < DAY:
            keep.add(i)
            continue
        when = datetime.fromtimestamp(stamps[i])
        if age < 7 * DAY:
            slot: tuple[str, Any] = ("day", when.date())
        elif age < 30 * DAY:
            slot = ("week", when.isocalendar()[:2])
        else:
            slot = ("month", (when.year, when.month))
        if slot not in seen:  # newest first: the first one met in a slot is its newest
            seen.add(slot)
            keep.add(i)
    return keep


# ---- editing sessions ----------------------------------------------------------------------


class Sessions:
    """When a save starts a new editing session (so the text before it is worth keeping): the
    first save of a note since the app started, or one after ``gap`` seconds without a save."""

    def __init__(self, gap: float = SESSION_GAP_S, clock: Callable[[], float] = time.time) -> None:
        self._gap, self._clock = gap, clock
        self._last: dict[str, float] = {}

    def starts(self, path: str) -> bool:
        now = self._clock()
        last = self._last.get(path)
        self._last[path] = now
        return last is None or now - last > self._gap

    def renamed(self, old: str, new: str) -> None:
        if old in self._last:
            self._last[new] = self._last.pop(old)


# ---- the store -----------------------------------------------------------------------------


class History:
    def __init__(
        self,
        vault_root: Path,
        *,
        cap_bytes: int = CAP_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db_path = vault_root / META_DIR / "history.db"
        self._cap, self._clock = cap_bytes, clock
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
            db.executescript(_SCHEMA)
            self._db = db
        except sqlite3.Error:
            log.exception("version history is off: cannot open %s", self.db_path)

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    # ---- reading ---------------------------------------------------------------------------

    def _rows(self, path: str) -> list[_Row]:
        """The note's versions, newest first."""
        assert self._db is not None
        found = self._db.execute(
            "SELECT id, ts, reason, sha, whole, data FROM versions WHERE path=? "
            "ORDER BY ts DESC, id DESC",
            (path,),
        ).fetchall()
        return [_Row(r[0], r[1], r[2], r[3], bool(r[4]), r[5]) for r in found]

    def versions(self, path: str) -> list[Version]:
        """The note's versions, newest first."""
        with self._lock:
            if self._db is None:
                return []
            return [Version(r.id, r.ts, r.reason) for r in self._rows(path)]

    def text(self, path: str, version_id: int) -> str:
        """The text of one version (:class:`DamagedVersion` if it cannot be rebuilt exactly)."""
        with self._lock:
            if self._db is None:
                raise DamagedVersion("no history")
            texts = self._texts(self._rows(path), stop=version_id)
        if version_id not in texts:
            raise DamagedVersion("no such version")
        result = texts[version_id]
        if isinstance(result, DamagedVersion):
            raise result
        return result

    def all_texts(self, path: str) -> list[tuple[Version, str | DamagedVersion]]:
        """Every version of ``path`` with its text (or why it cannot be rebuilt), newest first."""
        with self._lock:
            if self._db is None:
                return []
            rows = self._rows(path)
            texts = self._texts(rows)
        return [(Version(r.id, r.ts, r.reason), texts[r.id]) for r in rows]

    def _texts(self, rows: list[_Row], stop: int | None = None) -> dict[int, str | DamagedVersion]:
        """Rebuild ``rows`` (newest first) into ``{id: text or DamagedVersion}``."""
        out: dict[int, str | DamagedVersion] = {}
        current: str | None = None
        for row in rows:
            try:
                if row.whole:
                    current = zlib.decompress(row.data).decode("utf-8")
                elif current is None:
                    raise DamagedVersion("no newer text to start from")
                else:
                    current = apply_diff(current, row.data)
                if sha(current) != row.sha:
                    raise DamagedVersion("text does not match its checksum")
                out[row.id] = current
            except (DamagedVersion, zlib.error, UnicodeDecodeError) as exc:
                out[row.id] = exc if isinstance(exc, DamagedVersion) else DamagedVersion(str(exc))
                current = None  # older diffs need this text: they are damaged too
            if row.id == stop:
                break
        return out

    # ---- writing ---------------------------------------------------------------------------

    def record(self, path: str, text: str, reason: str) -> bool:
        """Keep ``text`` as the newest version of ``path``. False if it equals the newest one
        (or history is unavailable). Never raises: history must not get in the way of saving."""
        with self._lock:
            if self._db is None:
                return False
            try:
                return self._record(path, text, reason)
            except (sqlite3.Error, DamagedVersion):
                log.exception("could not record a version of %s", path)
                return False

    def _record(self, path: str, text: str, reason: str) -> bool:
        assert self._db is not None
        digest = sha(text)
        rows = self._rows(path)
        if rows and rows[0].sha == digest:
            return False
        self._db.execute("BEGIN")
        try:
            if rows:
                newest = rows[0]
                older = zlib.decompress(newest.data).decode("utf-8")  # the newest is whole
                diffs_in_a_row = next((i for i, r in enumerate(rows) if r.whole and i), len(rows))
                if diffs_in_a_row < KEYFRAME:  # else it stays whole (a keyframe)
                    self._db.execute(
                        "UPDATE versions SET whole=0, data=? WHERE id=?",
                        (make_diff(text, older), newest.id),
                    )
            self._db.execute(
                "INSERT INTO versions(path, ts, reason, sha, whole, data) VALUES(?,?,?,?,1,?)",
                (path, self._clock(), reason, digest, zlib.compress(text.encode("utf-8"))),
            )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        self._thin(path)
        self._enforce_cap()
        return True

    def _thin(self, path: str) -> None:
        rows = self._rows(path)
        keep = kept_versions([r.ts for r in rows], self._clock())
        if len(keep) < len(rows):
            self._rewrite(path, [r for i, r in enumerate(rows) if i in keep], rows)

    def _rewrite(self, path: str, kept: list[_Row], rows: list[_Row]) -> None:
        """Store only ``kept`` (newest first) of the note's ``rows``, as a fresh chain."""
        assert self._db is not None
        rebuilt = self._texts(rows)
        texts = {r.id: rebuilt[r.id] for r in kept}
        good = {vid: t for vid, t in texts.items() if isinstance(t, str)}
        if len(good) < len(texts):
            log.warning("history of %s is damaged; not thinning it", path)
            return
        self._db.execute("BEGIN")
        try:
            self._db.execute("DELETE FROM versions WHERE path=?", (path,))
            oldest_first = list(reversed(kept))
            for i, row in enumerate(oldest_first):
                text = good[row.id]
                newer = good[oldest_first[i + 1].id] if i + 1 < len(oldest_first) else None
                age = len(oldest_first) - 1 - i  # 0 = newest
                whole = newer is None or age % KEYFRAME == 0
                if whole or newer is None:
                    data = zlib.compress(text.encode("utf-8"))
                else:
                    data = make_diff(newer, text)
                self._db.execute(
                    "INSERT INTO versions(path, ts, reason, sha, whole, data) VALUES(?,?,?,?,?,?)",
                    (path, row.ts, row.reason, row.sha, int(whole), data),
                )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def size(self) -> int:
        with self._lock:
            if self._db is None:
                return 0
            return int(
                self._db.execute("SELECT COALESCE(SUM(length(data)),0) FROM versions").fetchone()[0]
            )

    def _enforce_cap(self) -> None:
        """Past the cap: drop the oldest versions (never a note's newest) until under it."""
        assert self._db is not None
        total = self.size()
        if total <= self._cap:
            return
        candidates = self._db.execute(
            "SELECT id, path, length(data) FROM versions v WHERE ts < "
            "(SELECT MAX(ts) FROM versions w WHERE w.path = v.path) ORDER BY ts"
        ).fetchall()
        dropped: dict[str, set[int]] = {}
        for vid, path, length in candidates:
            if total <= self._cap:
                break
            dropped.setdefault(path, set()).add(vid)
            total -= length
        for path, ids in dropped.items():
            rows = self._rows(path)
            self._rewrite(path, [r for r in rows if r.id not in ids], rows)

    def renamed(self, old: str, new: str) -> None:
        """A note or folder was renamed or moved: its history (and its notes') follows."""
        with self._lock:
            if self._db is None:
                return
            try:
                self._db.execute(
                    "UPDATE versions SET path = ? || substr(path, ?) "
                    "WHERE path = ? OR substr(path, 1, ?) = ?",
                    (new, len(old) + 1, old, len(old) + 1, old + "/"),
                )
            except sqlite3.Error:
                log.exception("could not move the history of %s", old)
