import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from watchdog.events import (
    DirCreatedEvent,
    DirModifiedEvent,
    DirMovedEvent,
    FileClosedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
)

from paper_pile.core.events import EventBus
from paper_pile.core.watcher import TOPIC, FsEvent, VaultWatcher, translate

ROOT = Path("/vault")


def t(event: object) -> FsEvent | None:
    return translate(ROOT, event)  # type: ignore[arg-type]


# ---- translate(): pure filtering / mapping ---------------------------------------------


def test_created_modified_deleted_note() -> None:
    assert t(FileCreatedEvent("/vault/a.md")) == FsEvent("created", "a.md", False)
    assert t(FileModifiedEvent("/vault/d/b.txt")) == FsEvent("modified", "d/b.txt", False)
    assert t(FileDeletedEvent("/vault/d/b.txt")) == FsEvent("deleted", "d/b.txt", False)


def test_folder_events() -> None:
    assert t(DirCreatedEvent("/vault/new")) == FsEvent("created", "new", True)
    assert t(DirModifiedEvent("/vault/new")) is None  # noise: children report themselves


@pytest.mark.parametrize(
    "path",
    [
        "/vault/.trash/2026/a.md",
        "/vault/.paper-pile/index.db",
        "/vault/.a.md.k3j2.tmp",  # atomic-write temp file
        "/vault/.hidden.md",
        "/vault/d/.x.assets/pic.png",
        "/vault/pic.png",
        "/vault/script.py",
        "/vault",  # the root itself
        "/elsewhere/a.md",
    ],
)
def test_uninteresting_paths_are_dropped(path: str) -> None:
    assert t(FileCreatedEvent(path)) is None
    assert t(FileModifiedEvent(path)) is None


def test_non_change_events_are_dropped() -> None:
    assert t(FileClosedEvent("/vault/a.md")) is None


def test_move_inside_vault() -> None:
    assert t(FileMovedEvent("/vault/a.md", "/vault/d/b.md")) == FsEvent(
        "moved", "d/b.md", False, "a.md"
    )
    assert t(DirMovedEvent("/vault/x", "/vault/y")) == FsEvent("moved", "y", True, "x")


def test_move_into_trash_is_a_delete_and_out_of_trash_a_create() -> None:
    assert t(FileMovedEvent("/vault/a.md", "/vault/.trash/s/a.md")) == FsEvent(
        "deleted", "a.md", False
    )
    assert t(FileMovedEvent("/vault/.trash/s/a.md", "/vault/a.md")) == FsEvent(
        "created", "a.md", False
    )
    assert t(FileMovedEvent("/vault/.trash/s/a.md", "/vault/.trash/t/a.md")) is None


def test_rename_to_or_from_a_non_note_extension() -> None:
    assert t(FileMovedEvent("/vault/a.md", "/vault/a.png")) == FsEvent("deleted", "a.md", False)
    assert t(FileMovedEvent("/vault/a.png", "/vault/a.md")) == FsEvent("created", "a.md", False)


# ---- real observer ---------------------------------------------------------------------


class Collector:
    def __init__(self) -> None:
        self.events: list[FsEvent] = []
        self.batches = 0
        self._cond = threading.Condition()

    def __call__(self, events: list[FsEvent]) -> None:
        with self._cond:
            self.events.extend(events)
            self.batches += 1
            self._cond.notify_all()

    def wait_for(self, predicate: Callable[[list[FsEvent]], bool], timeout: float = 4.0) -> bool:
        deadline = time.monotonic() + timeout
        with self._cond:
            while not predicate(self.events):
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)
        return True

    def quiet(self, seconds: float = 0.6) -> bool:
        """True if nothing arrives for ``seconds``."""
        with self._cond:
            before = len(self.events)
            self._cond.wait(seconds)
            return len(self.events) == before


@pytest.fixture
def watching(tmp_path: Path) -> Iterator[tuple[Path, Collector, VaultWatcher]]:
    root = tmp_path / "vault"
    root.mkdir()
    bus = EventBus()
    got = Collector()
    bus.subscribe(TOPIC, lambda events: got(events))
    w = VaultWatcher(root, bus, debounce=0.05)
    assert w.start()
    time.sleep(0.2)  # let inotify settle
    yield root, got, w
    w.stop()


def has(kind: str, path: str) -> Callable[[list[FsEvent]], bool]:
    return lambda evs: any(e.kind == kind and e.path == path for e in evs)


def test_create_modify_delete_note(watching: tuple[Path, Collector, VaultWatcher]) -> None:
    root, got, _ = watching
    note = root / "idea.md"
    note.write_text("one")
    assert got.wait_for(has("created", "idea.md"))
    note.write_text("two")
    assert got.wait_for(has("modified", "idea.md"))
    note.unlink()
    assert got.wait_for(has("deleted", "idea.md"))


def test_folder_and_nested_note(watching: tuple[Path, Collector, VaultWatcher]) -> None:
    root, got, _ = watching
    (root / "d").mkdir()
    assert got.wait_for(has("created", "d"))
    (root / "d" / "n.md").write_text("x")
    assert got.wait_for(has("created", "d/n.md"))


def test_rename_is_reported_as_moved(watching: tuple[Path, Collector, VaultWatcher]) -> None:
    root, got, _ = watching
    (root / "a.md").write_text("x")
    assert got.wait_for(has("created", "a.md"))
    (root / "a.md").rename(root / "b.md")
    assert got.wait_for(lambda evs: FsEvent("moved", "b.md", False, "a.md") in evs)


def test_hidden_and_non_note_changes_stay_silent(
    watching: tuple[Path, Collector, VaultWatcher],
) -> None:
    root, got, _ = watching
    (root / ".trash").mkdir()
    (root / ".trash" / "old.md").write_text("x")
    (root / ".paper-pile").mkdir()
    (root / ".paper-pile" / "index.db").write_text("x")
    (root / ".tmp-note.md.abc.tmp").write_text("x")
    (root / "pic.png").write_bytes(b"png")
    assert got.quiet(0.8)
    assert got.events == []


def test_burst_is_coalesced(watching: tuple[Path, Collector, VaultWatcher]) -> None:
    root, got, _ = watching
    for i in range(20):
        (root / f"n{i}.md").write_text("x")
    assert got.wait_for(lambda evs: len({e.path for e in evs if e.kind == "created"}) == 20)
    assert got.batches < 20  # far fewer batches than files
    assert len(got.events) == len(set(got.events))  # no duplicate entries within the stream


def test_atomic_write_by_the_app_reports_only_the_note(
    watching: tuple[Path, Collector, VaultWatcher],
) -> None:
    from paper_pile.core.fsutil import atomic_write_bytes

    root, got, _ = watching
    atomic_write_bytes(root / "saved.md", b"hello")
    assert got.wait_for(lambda evs: any(e.path == "saved.md" for e in evs))
    assert {e.path for e in got.events} == {"saved.md"}  # the hidden temp file never leaks


def test_stop_ends_delivery(watching: tuple[Path, Collector, VaultWatcher]) -> None:
    root, got, w = watching
    w.stop()
    (root / "late.md").write_text("x")
    assert got.quiet(0.8)
    assert got.events == []


def test_dispatch_decides_where_delivery_runs(tmp_path: Path) -> None:
    bus = EventBus()
    delivered = threading.Event()
    bus.subscribe(TOPIC, lambda events: delivered.set())
    queued: list[Callable[[], None]] = []
    w = VaultWatcher(tmp_path, bus, debounce=0.05, dispatch=queued.append)
    assert w.start()
    try:
        time.sleep(0.2)
        (tmp_path / "a.md").write_text("x")
        deadline = time.monotonic() + 4
        while not queued and time.monotonic() < deadline:
            time.sleep(0.05)
        assert queued and not delivered.is_set()  # nothing published until the owner runs it
        queued[0]()
        assert delivered.is_set()
    finally:
        w.stop()
