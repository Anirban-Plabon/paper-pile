"""The ordered list of open note tabs. Pure bookkeeping: no UI, no files.

Rules (PLAN §4.4): every note has at most one tab, opening a note that is already open just
focuses its tab, there are no preview tabs, closing the active tab activates its right
neighbour (else the left one), and a rename or move keeps the tab. Tab ids are never reused,
so UI code can use them as stable keys. Pinned tabs always come first (a drag never mixes the
two groups).
"""

from dataclasses import dataclass


@dataclass(slots=True)
class TabEntry:
    id: int
    path: str  # vault-relative, POSIX
    pinned: bool = False

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


class TabList:
    def __init__(self) -> None:
        self._tabs: list[TabEntry] = []
        self._next_id = 1
        self.active: int | None = None

    # ---- queries -------------------------------------------------------------------------

    @property
    def tabs(self) -> list[TabEntry]:
        return list(self._tabs)

    @property
    def paths(self) -> list[str]:
        return [t.path for t in self._tabs]

    @property
    def active_tab(self) -> TabEntry | None:
        return self.get(self.active) if self.active is not None else None

    def get(self, tab_id: int) -> TabEntry | None:
        return next((t for t in self._tabs if t.id == tab_id), None)

    def find(self, path: str) -> TabEntry | None:
        return next((t for t in self._tabs if t.path == path), None)

    def under(self, path: str) -> list[TabEntry]:
        """Tabs for ``path`` itself or anything inside it (when ``path`` is a folder)."""
        return [t for t in self._tabs if t.path == path or t.path.startswith(path + "/")]

    def titles(self) -> dict[int, tuple[str, str | None]]:
        """``{id: (file name, folder hint)}``; the hint is only set when names collide."""
        counts: dict[str, int] = {}
        for t in self._tabs:
            counts[t.name] = counts.get(t.name, 0) + 1
        out: dict[int, tuple[str, str | None]] = {}
        for t in self._tabs:
            parent = t.path.rsplit("/", 1)[0] if "/" in t.path else ""
            out[t.id] = (t.name, (parent or "/") if counts[t.name] > 1 else None)
        return out

    # ---- changes -------------------------------------------------------------------------

    def open(self, path: str) -> tuple[TabEntry, bool]:
        """Return ``(tab, created)``. A new tab goes to the end; neither case activates it."""
        existing = self.find(path)
        if existing is not None:
            return existing, False
        tab = TabEntry(self._next_id, path)
        self._next_id += 1
        self._tabs.append(tab)
        return tab, True

    def activate(self, tab_id: int | None) -> None:
        if tab_id is not None and self.get(tab_id) is None:
            raise KeyError(tab_id)
        self.active = tab_id

    def close(self, tab_id: int) -> int | None:
        """Remove a tab. If it was active, activate its right neighbour, else the left one.

        Returns the active tab id afterwards (``None`` when no tabs remain).
        """
        index = next((i for i, t in enumerate(self._tabs) if t.id == tab_id), None)
        if index is None:
            return self.active
        del self._tabs[index]
        if self.active == tab_id:
            if not self._tabs:
                self.active = None
            else:
                self.active = self._tabs[min(index, len(self._tabs) - 1)].id
        return self.active

    def move(self, src_id: int, dst_id: int, *, after: bool) -> bool:
        """Put tab ``src_id`` just before (or after) tab ``dst_id``. False if nothing changed."""
        if src_id == dst_id:
            return False
        src = self.get(src_id)
        if src is None or self.get(dst_id) is None:
            return False
        before = [t.id for t in self._tabs]
        self._tabs.remove(src)
        at = next(i for i, t in enumerate(self._tabs) if t.id == dst_id)
        self._tabs.insert(at + 1 if after else at, src)
        self._group()
        return [t.id for t in self._tabs] != before

    def set_pinned(self, tab_id: int, pinned: bool) -> bool:
        """Pin a tab (it joins the end of the pinned group) or unpin it (it becomes the first
        unpinned tab). False if nothing changed."""
        tab = self.get(tab_id)
        if tab is None or tab.pinned == pinned:
            return False
        self._tabs.remove(tab)
        tab.pinned = pinned
        self._tabs.insert(sum(t.pinned for t in self._tabs), tab)
        return True

    def _group(self) -> None:
        self._tabs.sort(key=lambda t: not t.pinned)  # stable: each group keeps its order

    def rename_prefix(self, old: str, new: str) -> list[TabEntry]:
        """A note or folder was renamed/moved: re-point the tabs inside it; returns them."""
        changed = self.under(old)
        for t in changed:
            t.path = new + t.path[len(old) :]
        return changed

    def cycle(self, step: int) -> int | None:
        """Id of the tab ``step`` places from the active one, wrapping around."""
        if not self._tabs:
            return None
        ids = [t.id for t in self._tabs]
        if self.active not in ids:
            return ids[0]
        return ids[(ids.index(self.active) + step) % len(ids)]
