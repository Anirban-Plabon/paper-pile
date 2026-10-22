"""Merging one note into another (the note menu's "Merge into…").

``source``'s body (its front matter dropped) is appended to ``target`` under a blank line, and
``source`` is then deleted by the caller (to the trash). The rule for links is the one of
``core/rewrite.py``: **every link keeps pointing at the note it pointed at** — except links to
``source``, which now point at ``target``, where its text lives:

- links in the appended body were written from ``source``'s folder: they are rewritten as if the
  text had moved to ``target`` (relative paths, and its images, which move to ``target``'s images
  folder — the caller moves the files with ``assets.move_assets``);
- links to ``source`` in every other note (and in ``target`` itself) are repointed at ``target``.

Pure: callers pass the texts and write the results.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from paper_pile.core.parser import body_start
from paper_pile.core.rewrite import apply_edits, plan_note


@dataclass(slots=True)
class MergePlan:
    text: str  # the target's new text
    updated: dict[str, str] = field(default_factory=dict)  # other notes whose links changed
    skipped: int = 0  # links that needed an edit but could not be located safely


def _rewritten(
    text: str, was: str, now: str, moves: Mapping[str, str], before: set[str], after: set[str]
) -> tuple[str, int]:
    if not now.lower().endswith(".md"):
        return text, 0  # plain text has no links
    edits, skipped = plan_note(text, was, now, moves, before, after)
    return (apply_edits(text, edits) if edits else text), skipped


def join_texts(target_text: str, body: str) -> str:
    """``body`` appended to ``target_text`` with one blank line between them."""
    head, tail = target_text.rstrip("\n"), body.strip("\n")
    if not tail:
        return target_text
    if not head:
        return tail + "\n"
    return f"{head}\n\n{tail}\n"


def plan_merge(
    source: str,
    target: str,
    source_text: str,
    target_text: str,
    paths: Collection[str],
    others: Mapping[str, str],
) -> MergePlan:
    """The merge of ``source`` into ``target``.

    ``paths``: every note path before the merge; ``others``: the texts of notes that may link to
    ``source`` (``source`` and ``target`` themselves are ignored there).
    """
    before = set(paths) | {source, target}
    after = before - {source}
    moves = {source: target}
    body = source_text.replace("\r\n", "\n")[body_start(source_text.replace("\r\n", "\n")) :]
    body, skipped = _rewritten(body, source, target, moves, before, after)
    own, own_skipped = _rewritten(target_text, target, target, moves, before, after)
    plan = MergePlan(join_texts(own, body), skipped=skipped + own_skipped)
    for path, text in others.items():
        if path in (source, target):
            continue
        new, missed = _rewritten(text, path, path, moves, before, after)
        plan.skipped += missed
        if new != text:
            plan.updated[path] = new
    return plan
