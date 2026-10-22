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


@dataclass(frozen=True, slots=True)
class TaggedNote:
    path: str
    title: str
    tags: tuple[str, ...]  # the matching tags as written in the note (``a/b`` for ``#a``)


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
        """Bring the index in line with the vault: new/changed files indexed, gone ones removed."""
        added = updated = 0
        with self._lock:
            known = {
                path: (mtime, digest)
                for path, mtime, digest in self._db.execute("SELECT path, mtime, hash FROM notes")
            }
            seen: set[str] = set()
            self._db.execute("BEGIN")
            try:
                for rel in self.vault.walk_notes():
                    seen.add(rel)
                    outcome = self._index_file(rel, known.get(rel))
                    added += outcome == "added"
                    updated += outcome == "updated"
                gone = [p for p in known if p not in seen]
                for rel in gone:
                    self._remove(rel)
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return SyncResult(added, updated, len(gone))

    def update_note(self, rel: str) -> bool:
        """Re-index one note (after a save or an outside change); False if it is gone."""
        with self._lock:
            if not self.vault.exists(rel):
                self.remove_note(rel)
                return False
            row = self._db.execute("SELECT mtime, hash FROM notes WHERE path=?", (rel,)).fetchone()
            self._db.execute("BEGIN")
            try:
                self._index_file(rel, row, force=True)
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

    def _index_file(self, rel: str, known: tuple[float, str] | None, *, force: bool = False) -> str:
        """Index one file inside the caller's transaction. Returns added/updated/same/skipped."""
        try:
            mtime = self.vault.resolve(rel).stat().st_mtime
            if known and not force and known[0] == mtime:
                return "same"
            text = self.vault.read_text(rel)
        except (VaultError, OSError):
            log.warning("could not index %s", rel)
            return "skipped"
        digest = hashlib.sha256(text.encode()).hexdigest()
        if known and known[1] == digest:
            self._db.execute("UPDATE notes SET mtime=? WHERE path=?", (mtime, rel))
            return "same"
        tokens = parse(text)  # once: title, links and tags all read it
        title = note_title(rel, text, tokens)
        if known:
            self._remove(rel)
        cur = self._db.execute(
            "INSERT INTO notes(path, title, mtime, hash) VALUES(?,?,?,?)",
            (rel, title, mtime, digest),
        )
        note_id = cur.lastrowid
        self._db.execute(
            "INSERT INTO notes_fts(path, title, body) VALUES(?,?,?)",
            (rel, title, search_body(text, tokens)),
        )
        self._db.executemany(
            "INSERT INTO links(src_id, dst_raw, dst_key, dst_path, kind, line) "
            "VALUES(?,?,?,NULL,?,?)",
            [
                (note_id, ref.raw, _dst_key(ref), ref.kind, ref.line)
                for ref in note_links(text, tokens)
            ],
        )
        if rel.lower().endswith(".md"):
            self._db.executemany(
                "INSERT INTO tags(note_id, tag, norm) VALUES(?,?,?)",
                [(note_id, tag, norm_tag(tag)) for tag in note_tags(text, tokens)],
            )
        return "updated" if known else "added"

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
                "SELECT n.path, n.title, l.kind, l.line, l.dst_raw FROM links l "
                f"JOIN notes n ON n.id=l.src_id WHERE l.dst_key IN ({marks}) AND n.path != ? "
                "ORDER BY n.path, l.line, l.rowid",
                (*keys, target),
            ).fetchall()
            paths = {r[0] for r in self._db.execute("SELECT path FROM notes")}
        found = []
        for src, title, kind, line, raw in rows:
            if kind == "wiki":
                parsed = parse_wikilink(raw)
                hit = parsed is not None and resolve_wikilink(parsed.note, src, paths) == target
            else:
                hit = resolve_md_link(raw, src, paths) == target
            if hit:
                found.append(Backlink(src, title, kind, line, raw))
        return found

    def search(self, query: str, limit: int = 50) -> list[SearchHit]:
        """Full-text search over title and body, best match first. Free text is safe to pass."""
        match = fts_query(query)
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
