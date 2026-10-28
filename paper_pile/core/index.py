"""SQLite cache: notes, links, FTS5 search. Fully rebuildable from the vault.

The index never holds anything the vault files do not: delete ``.paper-pile/index.db`` and
:meth:`Index.sync` rebuilds it. A corrupt or old-schema database is discarded and rebuilt.
"""

import hashlib
import logging
import re
import sqlite3
import threading
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from markdown_it.token import Token

from paper_pile.core.links import (
    link_keys,
    norm_name,
    parse_wikilink,
    resolve_md_link,
    resolve_wikilink,
)
from paper_pile.core.parser import LinkRef, front_matter, note_links, note_tags, parse
from paper_pile.core.tags import norm_tag
from paper_pile.core.vault import META_DIR, Vault, VaultError

log = logging.getLogger("paper_pile.index")

SCHEMA_VERSION = "4"  # 3: tags; 4: search body without front matter / heading marks
_SCHEMA = """
CREATE TABLE notes(id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
                   mtime REAL NOT NULL, hash TEXT NOT NULL);
CREATE TABLE links(src_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                   dst_raw TEXT NOT NULL, dst_key TEXT NOT NULL, dst_path TEXT, kind TEXT NOT NULL,
                   line INTEGER NOT NULL);
CREATE INDEX links_src ON links(src_id);
CREATE INDEX links_key ON links(dst_key);
CREATE VIRTUAL TABLE notes_fts USING fts5(
    path, title, body, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE tags(note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                  tag TEXT NOT NULL, norm TEXT NOT NULL);
CREATE INDEX tags_norm ON tags(norm);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class SyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0


@dataclass(frozen=True, slots=True)
class SearchHit:
    path: str
    title: str
    snippet: str  # matches wrapped in \x02 ... \x03


@dataclass(frozen=True, slots=True)
class Backlink:
    src: str  # the note that links here
    title: str
    kind: str
    line: int  # 1-based line of the link in ``src``
    raw: str  # the link as written
    mtime: float = 0.0  # ``src``'s mtime as indexed (to cache what was read from it)


@dataclass(frozen=True, slots=True)
class TaggedNote:
    path: str
    title: str
    tags: tuple[str, ...]  # the matching tags as written in the note (``a/b`` for ``#a``)


@dataclass(frozen=True, slots=True)
class _Read:
    """One file as the index stores it, read and parsed outside the lock."""

    rel: str
    mtime: float
    digest: str
    title: str | None = None  # None: the text is the indexed one, only the mtime moves
    body: str = ""
    links: tuple[tuple[str, str, str, int], ...] = ()  # raw, dst_key, kind, line
    tags: tuple[tuple[str, str], ...] = ()  # as written, normalised


@dataclass(frozen=True, slots=True)
class LinkRow:
    src: str
    dst_raw: str
    dst_path: str | None
    kind: str
    line: int


def note_title(rel: str, text: str, tokens: list[Token] | None = None) -> str:
    """Front-matter ``title``, else the first heading, else the file name without extension."""
    fm = front_matter(text, tokens)
    if fm and isinstance(fm.data.get("title"), str) and fm.data["title"].strip():
        return str(fm.data["title"]).strip()
    m = _HEADING.search(text)
    if m:
        return m.group(1).strip()
    return rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]


_HEADING_MARK = re.compile(r"(?m)^ {0,3}#{1,6}[ \t]+")


def search_body(text: str, tokens: list[Token]) -> str:
    """What the full-text search reads (and quotes in snippets): the note without its front
    matter and without the ``#`` marks of headings."""
    if tokens and tokens[0].type == "front_matter" and tokens[0].map:
        text = "\n".join(text.split("\n")[tokens[0].map[1] :])
    return _HEADING_MARK.sub("", text)


def _dst_key(ref: LinkRef) -> str:
    """What a link names, normalised, to find candidate links to a note without resolving all."""
    if ref.kind == "wiki":
        target = parse_wikilink(ref.raw)
        return norm_name(target.note).strip("/") if target else ""
    path = unquote(ref.raw).split("#", 1)[0].split("?", 1)[0]
    return norm_name(path.rsplit("/", 1)[-1])


def fts_query(user: str) -> str | None:
    """A safe FTS5 query from free text: every word quoted, the last one a prefix match."""
    words = _WORD.findall(user)
    if not words:
        return None
    quoted = [f'"{w}"' for w in words]
    quoted[-1] += "*"
    return " ".join(quoted)


_COMMON_WORDS = (  # left out of an any-words search
    "the and for are but not you all any can her was one our out has have had his how its may "
    "new now see who did get let put say she too use what when where which while with this that "
    "from into about there their them they then than your some more most also just like does "
    "will would could should please tell give show find notes note vault"
)
_COMMON = frozenset(_COMMON_WORDS.split())


def fts_any_query(user: str, most: int = 12) -> str | None:
    """A safe FTS5 query matching notes with ANY of the question's words (3+ letters, common
    words left out), for finding notes about a question rather than an exact phrase."""
    words = [w for w in _WORD.findall(user) if len(w) >= 3 and w.lower() not in _COMMON]
    if not words:
        return None
    return " OR ".join(f'"{w}"' for w in list(dict.fromkeys(words))[:most])


class Index:
    def __init__(self, vault: Vault) -> None:
        self.vault = vault
        self.db_path = vault.root / META_DIR / "index.db"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = self._open()

    # ---- lifecycle -------------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _open(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            db = self._connect()
            tables = db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
            if tables == 0:
                self._create(db)
                return db
            row = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row and row[0] == SCHEMA_VERSION:
                return db
            db.close()
        except sqlite3.DatabaseError:
            log.warning("index database unreadable; rebuilding")
        self._delete_files()
        db = self._connect()
        self._create(db)
        return db

    def _create(self, db: sqlite3.Connection) -> None:
        db.executescript(_SCHEMA)
        db.execute("INSERT INTO meta VALUES('schema_version', ?)", (SCHEMA_VERSION,))

    def _delete_files(self) -> None:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(self.db_path) + suffix).unlink(missing_ok=True)

    @property
    def _db(self) -> sqlite3.Connection:
        """The connection, reopened on demand: a page that lost its websocket may come back and
        use the same index after :meth:`close` was called."""
        if self._conn is None:
            self._conn = self._open()
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def rebuild(self) -> SyncResult:
        """Drop everything and index the vault again."""
        with self._lock:
            self._db.close()
            self._conn = None
            self._delete_files()
            self._conn = self._open()
        return self.sync()

    # ---- writing ---------------------------------------------------------------------------

    def sync(self) -> SyncResult:
        """Bring the index in line with the vault: new/changed files indexed, gone ones removed.

        The walk, the reads and the parsing happen without the lock (the UI thread's queries
        must not wait for the disk); the lock is held only for the write. A row that changed
        since the snapshot was written meanwhile by :meth:`update_note` from a newer read, so it
        is kept; a file is only removed if it is still missing then.
        """
        with self._lock:
            known: dict[str, tuple[float, str]] = {
                path: (mtime, digest)
                for path, mtime, digest in self._db.execute("SELECT path, mtime, hash FROM notes")
            }
        seen: set[str] = set()
        reads: list[_Read] = []
        for rel in self.vault.walk_notes():
            seen.add(rel)
            read = self._read(rel, known.get(rel))
            if read is not None:
                reads.append(read)
        gone = [p for p in known if p not in seen]
        added = updated = removed = 0
        with self._lock:
            self._db.execute("BEGIN")
            try:
                for read in reads:
                    snapshot = known.get(read.rel)
                    if self._row(read.rel) != snapshot:
                        continue
                    self._write(read, snapshot)
                    added += snapshot is None
                    updated += snapshot is not None and read.title is not None
                for rel in gone:
                    if self._row(rel) == known[rel] and not self.vault.exists(rel):
                        self._remove(rel)
                        removed += 1
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return SyncResult(added, updated, removed)

    def update_note(self, rel: str) -> bool:
        """Re-index one note (after a save or an outside change); False if it is gone."""
        if not self.vault.exists(rel):
            self.remove_note(rel)
            return False
        with self._lock:
            row = self._row(rel)
        read = self._read(rel, row, force=True)
        if read is None:
            return True
        with self._lock:
            current = self._row(rel)
            if current is not None and current[0] > read.mtime:
                return True  # a newer version is indexed already
            if read.title is None and current != row:  # "same text" compared with an old row
                read = self._read(rel, None, force=True)
                if read is None:
                    return True
            self._db.execute("BEGIN")
            try:
                self._write(read, current)
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return True

    def remove_note(self, rel: str) -> None:
        with self._lock:
            self._db.execute("BEGIN")
            self._remove(rel)
            self._db.execute("COMMIT")

    def rename_note(self, old: str, new: str) -> None:
        """A note moved: keep its row (and so its links) under the new path."""
        with self._lock:
            self._db.execute("BEGIN")
            self._db.execute("UPDATE notes SET path=? WHERE path=?", (new, old))
            self._db.execute("UPDATE notes_fts SET path=? WHERE path=?", (new, old))
            self._db.execute("COMMIT")
        self.update_note(new)

    def _remove(self, rel: str) -> None:
        self._db.execute("DELETE FROM notes WHERE path=?", (rel,))  # links cascade
        self._db.execute("DELETE FROM notes_fts WHERE path=?", (rel,))

    def _row(self, rel: str) -> tuple[float, str] | None:
        """``(mtime, hash)`` of the indexed note (caller holds the lock)."""
        row = self._db.execute("SELECT mtime, hash FROM notes WHERE path=?", (rel,)).fetchone()
        return (row[0], row[1]) if row else None

    def _read(
        self, rel: str, known: tuple[float, str] | None, *, force: bool = False
    ) -> _Read | None:
        """Read and parse one file for the index, without touching the database. ``None``: its
        mtime is the indexed one (unless ``force``), or it could not be read."""
        try:
            mtime = self.vault.resolve(rel).stat().st_mtime
            if known and not force and known[0] == mtime:
                return None
            text = self.vault.read_text(rel)
        except (VaultError, OSError):
            log.warning("could not index %s", rel)
            return None
        digest = hashlib.sha256(text.encode()).hexdigest()
        if known and known[1] == digest:
            return _Read(rel, mtime, digest)  # same text: only the mtime moves
        tokens = parse(text)  # once: title, links and tags all read it
        tags = note_tags(text, tokens) if rel.lower().endswith(".md") else []
        return _Read(
            rel,
            mtime,
            digest,
            title=note_title(rel, text, tokens),
            body=search_body(text, tokens),
            links=tuple((r.raw, _dst_key(r), r.kind, r.line) for r in note_links(text, tokens)),
            tags=tuple((tag, norm_tag(tag)) for tag in tags),
        )

    def _write(self, read: _Read, current: tuple[float, str] | None) -> None:
        """Store one :meth:`_read` result inside the caller's transaction; ``current`` is the
        note's row as it is now."""
        if read.title is None:
            self._db.execute("UPDATE notes SET mtime=? WHERE path=?", (read.mtime, read.rel))
            return
        if current:
            self._remove(read.rel)
        cur = self._db.execute(
            "INSERT INTO notes(path, title, mtime, hash) VALUES(?,?,?,?)",
            (read.rel, read.title, read.mtime, read.digest),
        )
        note_id = cur.lastrowid
        self._db.execute(
            "INSERT INTO notes_fts(path, title, body) VALUES(?,?,?)",
            (read.rel, read.title, read.body),
        )
        self._db.executemany(
            "INSERT INTO links(src_id, dst_raw, dst_key, dst_path, kind, line) "
            "VALUES(?,?,?,NULL,?,?)",
            [(note_id, raw, key, kind, line) for raw, key, kind, line in read.links],
        )
        self._db.executemany(
            "INSERT INTO tags(note_id, tag, norm) VALUES(?,?,?)",
            [(note_id, tag, norm) for tag, norm in read.tags],
        )

    # ---- reading ---------------------------------------------------------------------------

    def paths(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._db.execute("SELECT path FROM notes ORDER BY path")]

    def title(self, rel: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT title FROM notes WHERE path=?", (rel,)).fetchone()
        return str(row[0]) if row else None

    def links_from(self, rel: str) -> list[LinkRow]:
        with self._lock:
            rows = self._db.execute(
                "SELECT n.path, l.dst_raw, l.dst_path, l.kind, l.line FROM links l "
                "JOIN notes n ON n.id=l.src_id WHERE n.path=? ORDER BY l.line, l.rowid",
                (rel,),
            ).fetchall()
        return [LinkRow(*r) for r in rows]

    def notes_with_tag(self, tag: str) -> list[TaggedNote]:
        """Notes tagged ``tag`` or a tag nested in it (``a`` finds ``a/b``), by title."""
        norm = norm_tag(tag)
        if not norm:
            return []
        with self._lock:
            rows = self._db.execute(
                "SELECT n.path, n.title, group_concat(DISTINCT t.tag) FROM tags t "
                "JOIN notes n ON n.id=t.note_id "
                "WHERE t.norm=? OR substr(t.norm, 1, ?)=? "
                "GROUP BY n.id ORDER BY lower(n.title), n.path",
                (norm, len(norm) + 1, norm + "/"),
            ).fetchall()
        return [TaggedNote(r[0], r[1], tuple(str(r[2]).split(","))) for r in rows]

    def tags_of(self, rel: str) -> list[str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT t.tag FROM tags t JOIN notes n ON n.id=t.note_id WHERE n.path=? "
                "ORDER BY t.rowid",
                (rel,),
            ).fetchall()
        return [r[0] for r in rows]

    def link_sources(self, keys: Collection[str]) -> set[str]:
        """Notes holding a link that names any of ``keys`` (see :func:`links.link_keys`)."""
        if not keys:
            return set()
        marks = ",".join("?" * len(keys))
        with self._lock:
            rows = self._db.execute(
                "SELECT DISTINCT n.path FROM links l JOIN notes n ON n.id=l.src_id "
                f"WHERE l.dst_key IN ({marks})",
                tuple(keys),
            ).fetchall()
        return {r[0] for r in rows}

    def backlinks(self, target: str) -> list[Backlink]:
        """Notes that link to ``target`` (not counting itself), with the link's line.

        Candidates come from the name each link uses; each is then resolved the way a click
        would resolve it, so a link only counts if it really leads to ``target``.
        """
        keys = link_keys([target])
        marks = ",".join("?" * len(keys))
        with self._lock:
            rows = self._db.execute(
                "SELECT n.path, n.title, l.kind, l.line, l.dst_raw, n.mtime FROM links l "
                f"JOIN notes n ON n.id=l.src_id WHERE l.dst_key IN ({marks}) AND n.path != ? "
                "ORDER BY n.path, l.line, l.rowid",
                (*keys, target),
            ).fetchall()
            paths = {r[0] for r in self._db.execute("SELECT path FROM notes")}
        found = []
        for src, title, kind, line, raw, mtime in rows:
            if kind == "wiki":
                parsed = parse_wikilink(raw)
                hit = parsed is not None and resolve_wikilink(parsed.note, src, paths) == target
            else:
                hit = resolve_md_link(raw, src, paths) == target
            if hit:
                found.append(Backlink(src, title, kind, line, raw, mtime))
        return found

    def search(self, query: str, limit: int = 50, *, any_words: bool = False) -> list[SearchHit]:
        """Full-text search over title and body, best match first. Free text is safe to pass.
        ``any_words``: notes with any of the words (the AI's ``@vault``), not all of them."""
        match = fts_any_query(query) if any_words else fts_query(query)
        if match is None:
            return []
        with self._lock:
            try:
                rows = self._db.execute(
                    "SELECT path, title, snippet(notes_fts, 2, char(2), char(3), '…', 12) "
                    "FROM notes_fts WHERE notes_fts MATCH ? "
                    "ORDER BY bm25(notes_fts, 0, 4, 1) LIMIT ?",
                    (match, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                log.warning("bad search query %r", query)
                return []
        return [SearchHit(*r) for r in rows]
