"""What one step gives back to the chat (PLAN_vault_agent §7, P30.20): the text to show,
the notes it is about, the cited sources, a table when one was built, and hints. The UI
renders the structured parts (result blocks, pills, chips); ``text`` is the plain markdown
form for the chat history and for a front end that shows only text. No UI imports.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from paper_pile.core.ai.vault.cite import Checked, Source
from paper_pile.core.ai.vault.results import ResultSet

if TYPE_CHECKING:
    from paper_pile.core.ai.vault.edits import EditBatch


@dataclass(frozen=True, slots=True)
class Hint:
    """A next step offered as a chip, made from data — never a model call (§3.5)."""

    label: str
    kind: str  # "scope" | "action" | "near" | "maybe"
    value: str = ""  # what picking it means (a folder, a tag, an action name…)


@dataclass(slots=True)
class Table:
    columns: list[str]
    rows: list[list[str]] = field(default_factory=list)
    sources: list[int] = field(default_factory=list)  # per row: the label of its note


@dataclass(slots=True)
class Reply:
    text: str
    results: ResultSet = field(default_factory=ResultSet)
    sources: list[Source] = field(default_factory=list)
    checked: Checked | None = None
    table: Table | None = None
    hints: list[Hint] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    review: "EditBatch | None" = None  # changes to notes waiting for the user (M6)

    @property
    def unverified_note(self) -> str:
        """The footer line for citations that could not be checked ("" when all are fine)."""
        if self.checked is None:
            return ""
        bad = len(self.checked.unverified) + len(self.checked.dropped)
        if not bad:
            return ""
        return f"{bad} citation{'s' if bad > 1 else ''} could not be verified."


def _folder(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def locate(results: ResultSet) -> Reply:
    """The notes found, as a list with why each is there — no model call (P30.20)."""
    sure, maybe = results.sure(), results.maybe()
    if not sure and not maybe:
        return Reply("No notes found.", results)
    lines: list[str] = []
    for i, item in enumerate(sure, 1):
        where = f" — `{_folder(item.path)}`" if _folder(item.path) else ""
        why = f": {item.reason}" if item.reason else ""
        lines.append(f"{i}. **{item.title}**{where}{why}")
    if maybe:
        lines.append("")
        lines.append("Might also be related:" if sure else "Possibly related:")
        for item in maybe:
            why = f": {item.reason}" if item.reason else ""
            lines.append(f"- {item.title}{why}")
    head = f"Found {len(sure)} note{'s' if len(sure) != 1 else ''}." if sure else ""
    return Reply("\n".join([head, "", *lines]).strip(), results)
