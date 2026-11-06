"""The chat's last result set (PLAN_vault_agent §5.5, P30.12): what the agent found, kept
compact (paths, titles, short reasons — never note text), so a follow-up ("those", "the second
one", "only the 2025 ones") works on it and the conversation stays small.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

Relevance = Literal["yes", "maybe"]


@dataclass(frozen=True, slots=True)
class ResultItem:
    path: str
    title: str
    reason: str = ""  # one line: why it is in the set
    relevance: Relevance = "yes"
    heading: str = ""  # the section it was found in, when known


@dataclass(slots=True)
class ResultSet:
    """Numbered from 1 for the user and the model."""

    request: str = ""  # what the set answers (the step's summary)
    items: list[ResultItem] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.items)

    @property
    def paths(self) -> list[str]:
        return [i.path for i in self.items]

    def sure(self) -> list[ResultItem]:
        return [i for i in self.items if i.relevance == "yes"]

    def maybe(self) -> list[ResultItem]:
        return [i for i in self.items if i.relevance == "maybe"]

    def pick(self, which: object) -> list[ResultItem]:
        """Items a follow-up refers to: ``"all"``, ``"yes"`` / ``"maybe"``, 1-based numbers
        (``[2, 3]``, ``"2"``), or paths. Unknown numbers and paths are left out."""
        if which in (None, "all", "", []):
            return list(self.items)
        if which in ("yes", "maybe"):
            return [i for i in self.items if i.relevance == which]
        picks: Iterable[object] = which if isinstance(which, list) else [which]
        out: list[ResultItem] = []
        for p in picks:
            if isinstance(p, bool):
                continue
            n = int(p) if isinstance(p, int) or (isinstance(p, str) and p.isdigit()) else None
            if n is not None:
                if 1 <= n <= len(self.items):
                    out.append(self.items[n - 1])
            elif isinstance(p, str):
                out += [i for i in self.items if i.path == p]
        return list(dict.fromkeys(out))

    def narrowed(self, keep: Callable[[ResultItem], bool], request: str = "") -> "ResultSet":
        return ResultSet(request or self.request, [i for i in self.items if keep(i)])

    def without_paths(self, paths: Sequence[str]) -> "ResultSet":
        """The set with notes taken out (one renamed / deleted / made private since)."""
        gone = set(paths)
        return ResultSet(self.request, [i for i in self.items if i.path not in gone])

    def renamed(self, old: str, new: str) -> "ResultSet":
        return ResultSet(
            self.request, [replace(i, path=new) if i.path == old else i for i in self.items]
        )

    def compact(self) -> str:
        """The set as the model sees it in a follow-up: numbered lines, no note text."""
        lines = [f"Last result ({self.request}):" if self.request else "Last result:"]
        for n, i in enumerate(self.items, 1):
            mark = "" if i.relevance == "yes" else " (maybe)"
            why = f" — {i.reason}" if i.reason else ""
            lines.append(f"{n}. {i.title} [{i.path}]{mark}{why}")
        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        return {"request": self.request, "items": [asdict(i) for i in self.items]}

    @classmethod
    def from_json(cls, data: object) -> "ResultSet":
        if not isinstance(data, dict):
            return cls()
        items = []
        for raw in data.get("items", []):
            if isinstance(raw, dict) and isinstance(raw.get("path"), str):
                rel = raw.get("relevance")
                items.append(
                    ResultItem(
                        raw["path"],
                        str(raw.get("title", raw["path"])),
                        str(raw.get("reason", "")),
                        "maybe" if rel == "maybe" else "yes",
                        str(raw.get("heading", "")),
                    )
                )
        return cls(str(data.get("request", "")), items)
