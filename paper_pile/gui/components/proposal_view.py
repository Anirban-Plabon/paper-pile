"""What the editor's diff view (``tools/editor_src/proposal.js``) gets for an AI proposal
(PLAN §4.29): each change with its place (UTF-16 offsets, as CodeMirror counts), the reason the
AI gave, what the checks found, whether it is outside the selection, and the words that changed;
the notes for the bar ("Similar text in …", "Maybe also update …" with an Update button)."""

from typing import Any

from paper_pile.core.ai.proposals import Proposal, word_marks
from paper_pile.core.textpos import utf16_index


def _utf16(text: str, ranges: list[tuple[int, int]]) -> list[list[int]]:
    return [[utf16_index(text, a), utf16_index(text, b)] for a, b in ranges]


def proposal_payload(proposal: Proposal, text: str, readonly: bool) -> dict[str, Any]:
    hunks = []
    for h in proposal.hunks:
        marks = word_marks(h.old, h.new) if h.old and h.new else None
        base = utf16_index(text, h.start)
        hunks.append(
            {
                "id": h.id,
                "from": base,
                "to": utf16_index(text, h.end),
                "insert": h.new,
                "reason": h.reason,
                "outside": h.outside,
                "issues": [
                    {"severity": i.severity, "message": i.message}
                    for i in h.issues
                    if i.severity in ("warn", "fixed") and i.message
                ],
                "marksOld": [[base + a, base + b] for a, b in _utf16(h.old, marks[0])]
                if marks
                else [],
                "marksNew": _utf16(h.new, marks[1]) if marks else [],
            }
        )
    notes = [
        {"i": n, "kind": i.kind, "message": i.message, "update": i.kind == "maybe-update"}
        for n, i in enumerate(proposal.notes)
        if i.message
    ]
    return {"id": proposal.id, "hunks": hunks, "notes": notes, "readonly": readonly}
