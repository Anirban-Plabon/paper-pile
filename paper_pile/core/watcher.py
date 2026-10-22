"""Watch the vault for changes made outside the app and report them as batched events.

``watchdog`` (inotify on Linux) delivers raw events on its own thread; this module
  * drops everything the app never shows: hidden paths (``.trash``, ``.paper-pile``,
    ``.name.xxx.tmp`` left by atomic writes) and non-note files,
  * turns the rest into :class:`FsEvent` values with vault-relative POSIX paths,
  * coalesces bursts (one save is several raw events) into one batch, and
  * publishes the batch as ``vault.fs_changed(events=[...])`` on the given bus.

The bus is synchronous and would otherwise be called from the timer thread, so the owner
passes ``dispatch`` to run delivery where it wants (the GUI hops onto its event loop).
Core stays UI-free.
"""

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from paper_pile.core.events import EventBus
from paper_pile.core.vault import is_hidden_part, is_note_name

log = logging.getLogger("paper_pile.watcher")

TOPIC = "vault.fs_changed"
DEFAULT_DEBOUNCE_S = 0.15

Kind = Literal["created", "deleted", "modified", "moved"]
_HANDLED = frozenset({"created", "deleted", "modified", "moved"})


@dataclass(frozen=True, slots=True)
class FsEvent:
    kind: Kind
    path: str  # vault-relative, POSIX (the new path for "moved")
    is_dir: bool
    old_path: str | None = None  # only for "moved"


def _rel_parts(root: Path, raw: str | bytes) -> tuple[str, ...] | None:
    try:
        return Path(os.fsdecode(raw)).relative_to(root).parts
    except ValueError:
        return None


def _visible(parts: tuple[str, ...] | None, is_dir: bool) -> bool:
    if not parts or any(is_hidden_part(p, i) for i, p in enumerate(parts)):
        return False
    return is_dir or is_note_name(parts[-1])


def translate(root: Path, event: FileSystemEvent) -> FsEvent | None:
    """Map one raw watchdog event to an :class:`FsEvent`, or ``None`` if it is not interesting."""
    kind = event.event_type
    if kind not in _HANDLED:
        return None
    is_dir = event.is_directory
    src = _rel_parts(root, event.src_path)
    if kind == "moved":
        dst = _rel_parts(root, event.dest_path)
        src_ok, dst_ok = _visible(src, is_dir), _visible(dst, is_dir)
        if src_ok and dst_ok and src and dst:
            return FsEvent("moved", "/".join(dst), is_dir, "/".join(src))
        if src_ok and src:  # moved out of sight, e.g. into .trash: it is gone as far as we care
            return FsEvent("deleted", "/".join(src), is_dir)
        if dst_ok and dst:  # moved into sight, e.g. restored from .trash
            return FsEvent("created", "/".join(dst), is_dir)
        return None
    if kind == "modified" and is_dir:
        return None  # a folder "modifies" whenever its children change; the children say it better
    if not _visible(src, is_dir) or not src:
        return None
    return FsEvent(kind, "/".join(src), is_dir)  # type: ignore[arg-type]


class _Handler(FileSystemEventHandler):
    def __init__(self, sink: Callable[[FileSystemEvent], None]) -> None:
        self._sink = sink

    def on_any_event(self, event: FileSystemEvent) -> None:
        self._sink(event)


class VaultWatcher:
    def __init__(
        self,
        root: Path,
        bus: EventBus,
        *,
        debounce: float = DEFAULT_DEBOUNCE_S,
        dispatch: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.bus = bus
        self._debounce = debounce
        self._dispatch = dispatch or (lambda fn: fn())
        self._lock = threading.Lock()
        self._pending: list[FsEvent] = []
        self._timer: threading.Timer | None = None
        self._observer: Observer | None = None  # type: ignore[valid-type]

    def start(self) -> bool:
        """Begin watching. Returns False (and logs) if the OS refuses, e.g. inotify limits."""
        observer = Observer()
        observer.daemon = True
        try:
            observer.schedule(_Handler(self._on_raw), str(self.root), recursive=True)
            observer.start()
        except OSError:
            log.warning(
                "could not watch %s; external changes will not show live", self.root, exc_info=True
            )
            return False
        self._observer = observer
        return True

    def stop(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending.clear()
        observer, self._observer = self._observer, None
        if observer is not None:
            observer.stop()
            observer.join(timeout=2)

    # ---- internals -----------------------------------------------------------------------

    def _on_raw(self, raw: FileSystemEvent) -> None:
        event = translate(self.root, raw)
        if event is None:
            return
        with self._lock:
            if event not in self._pending:
                self._pending.append(event)
            if self._timer is None:  # bounded latency: the window starts at the first event
                self._timer = threading.Timer(self._debounce, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            batch, self._pending = self._pending, []
            self._timer = None
        if batch:
            self._dispatch(lambda: self.bus.publish(TOPIC, events=batch))
