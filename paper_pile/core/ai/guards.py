"""Checks on every change an AI edit makes (PLAN §4.29, ``docs/AI_EDITS.md`` §4.6), all in
Python, so what the model writes can be trusted to keep the note's shape whatever it does:

G1 no headings added or lost (a title the target did not have is removed); G3 links, code,
math, tags and URLs kept; G5 not more changed than the request asks for; G6 a list stays a
list, a table keeps its columns; G7 no context echoed back; G9 the language kept. (G2 / G8 —
wrappers and commentary — are ``cleanup.clean_reply``; G4 — code and math blocks — is
``write.fit_answer``; G10 — a finished, non-empty answer — is the edit run.) A check that fails
asks for one retry with feedback that names the problem; on the retry it becomes a warning, and
a change with a warning is never applied unseen. Pure; no UI imports.
"""

import difflib
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from paper_pile.core.ai.blocks import block_map
from paper_pile.core.ai.issues import Issue, Severity
from paper_pile.core.ai.protect import missing_tokens, protected_tokens
from paper_pile.core.parser import headings

Size = Literal["small", "medium", "large"]
SIZE_LIMIT: dict[Size, float] = {"small": 0.2, "medium": 0.6, "large": 1.0}
ECHO_SHARE = 0.6
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?|\S")
_HEADING_LINE = re.compile(r"^#{1,6}[ \t]+\S")
STRUCTURE_WORDS = ("heading", "title", "section", "headline", "subheading")
REMOVE_WORDS = ("remove", "delete", "drop", "unlink", "without", "strip", "get rid")


@dataclass(frozen=True, slots=True)
class GuardContext:
    """What the change was asked to be."""

    action: str  # "change", "add_after", "add_before"
    instruction: str = ""
    size: Size = "medium"
    new_section: bool = False
    level: int = 0  # the new section's heading level
    neighbours: tuple[str, ...] = ()  # context the model was told not to write
    translate: bool = False
    keep: tuple[str, ...] = field(default=())  # protected tokens named in the prompt

    @property
    def asks_structure(self) -> bool:
        return asked_for(self.instruction, STRUCTURE_WORDS)


def asked_for(instruction: str, words: Sequence[str]) -> bool:
    low = instruction.lower()
    return any(re.search(rf"\b{re.escape(w)}", low) for w in words)


def allowed_tokens(instruction: str) -> list[str]:
    """Protected tokens the instruction itself names together with a remove word: those may go."""
    if not asked_for(instruction, REMOVE_WORDS):
        return []
    return protected_tokens(instruction) + re.findall(r"#[\w/-]+|\[\[[^\]]+\]\]", instruction)


def change_share(old: str, new: str) -> float:
    """How much of ``old`` changed, by words (0: nothing, 1: everything)."""
    a, b = _WORD.findall(old), _WORD.findall(new)
    if not a and not b:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(a=a, b=b, autojunk=False).ratio()


def main_script(text: str) -> str:
    """The script most of ``text``'s letters are written in (LATIN, BENGALI, CJK, …)."""
    count: Counter[str] = Counter()
    for ch in text:
        if ch.isalpha():
            name = unicodedata.name(ch, "")
            script = name.split(" ")[0] if name else ""
            count["CJK" if script in ("CJK", "HIRAGANA", "KATAKANA", "HANGUL") else script] += 1
    return count.most_common(1)[0][0] if count else ""


def _shingles(text: str, n: int = 3) -> set[tuple[str, ...]]:
    words = [w.lower() for w in re.findall(r"[^\W_]+", text)]
    return {tuple(words[i : i + n]) for i in range(max(0, len(words) - n + 1))}


def _kinds(text: str) -> list[str]:
    """The text's block kinds, items of one list counted once."""
    out: list[str] = []
    last_list = ""
    for b in block_map(text):
        if b.kind == "item":
            if b.list_id != last_list:
                out.append("list")
            last_list = b.list_id
            continue
        last_list = ""
        out.append(b.kind)
    return out


def _columns(text: str) -> list[int]:
    return [
        b.text(text).split("\n", 1)[0].strip().strip("|").count("|") + 1
        for b in block_map(text)
        if b.kind == "table"
    ]


def check(
    ctx: GuardContext, old: str, new: str, *, retried: bool = False
) -> tuple[str, list[Issue]]:
    """``new`` repaired where that is safe, and what is still wrong with it (``old``: the text
    it replaces, "" for new text). After a retry nothing asks for another one."""
    issues: list[Issue] = []
    new = _g1_headings(ctx, old, new, issues)
    new = _g7_echo(ctx, new, issues)
    if old:
        _g3_tokens(ctx, old, new, issues)
        _g5_size(ctx, old, new, issues)
        _g6_kinds(ctx, old, new, issues)
        _g9_script(ctx, old, new, issues)
    if retried:
        issues = [_as_warning(i) for i in issues]
    return new, issues


def _as_warning(issue: Issue) -> Issue:
    if issue.severity != "retry":
        return issue
    return Issue(issue.kind, "warn", issue.message, issue.feedback, issue.data)


def _retry(kind: str, message: str, feedback: str) -> Issue:
    severity: Severity = "retry"
    return Issue(kind, severity, message, feedback)


def _g1_headings(ctx: GuardContext, old: str, new: str, issues: list[Issue]) -> str:
    had = [h.level for h in headings(old)] if old else []
    got = headings(new)
    if ctx.asks_structure:
        return new
    if ctx.new_section:
        extra = [h for h in got[1:] if h.level <= ctx.level]
        if not got or got[0].line != 1:
            issues.append(
                _retry(
                    "heading",
                    "The new section has no heading.",
                    f"Start with one heading line at level {ctx.level}.",
                )
            )
        elif extra:
            issues.append(
                _retry(
                    "heading",
                    "The new text has more than one section heading.",
                    f"Write one section: only one heading of level {ctx.level} or higher.",
                )
            )
        return new
    if not had:
        if got and got[0].line == 1:  # a title the target did not have: remove it
            first, _, rest = new.partition("\n")
            if _HEADING_LINE.match(first.strip()):
                new = rest.lstrip("\n")
                issues.append(Issue("heading", "fixed", "A heading the AI added was removed."))
                got = headings(new)
        if got:
            issues.append(_retry("heading", "The AI added a heading.", "Do not add headings."))
        return new
    levels = [h.level for h in got]
    if levels != had:
        wanted = ", ".join(f"level {n}" for n in had)
        issues.append(
            _retry(
                "heading",
                "The headings changed.",
                f"Keep the headings exactly as they are ({wanted}); add or remove none.",
            )
        )
    return new


def _g3_tokens(ctx: GuardContext, old: str, new: str, issues: list[Issue]) -> None:
    allowed = allowed_tokens(ctx.instruction)
    if ctx.translate:  # a translated link may change its alias, never its target
        old = re.sub(r"\[\[([^\]|]+)\|[^\]]*\]\]", r"[[\1]]", old)
        new = re.sub(r"\[\[([^\]|]+)\|[^\]]*\]\]", r"[[\1]]", new)
    lost = missing_tokens(old, new, allowed)
    if lost:
        names = ", ".join(dict.fromkeys(lost))
        issues.append(
            _retry("tokens", f"Lost: {names}", f"You dropped {names}. Keep them exactly.")
        )


def _g5_size(ctx: GuardContext, old: str, new: str, issues: list[Issue]) -> None:
    share = change_share(old, new)
    if share > SIZE_LIMIT[ctx.size]:
        issues.append(
            _retry(
                "size",
                f"Changed {round(share * 100)} % of the words (asked: "
                f"{'small fixes' if ctx.size == 'small' else 'some changes'}).",
                "Change only what the task asks for; keep every other word.",
            )
        )


def _g6_kinds(ctx: GuardContext, old: str, new: str, issues: list[Issue]) -> None:
    if ctx.asks_structure:
        return
    if _kinds(old) != _kinds(new):
        issues.append(Issue("kind", "warn", "The kind of text changed (a list, table or quote)."))
    elif _columns(old) != _columns(new):
        issues.append(Issue("kind", "warn", "A table's number of columns changed."))


def _g7_echo(ctx: GuardContext, new: str, issues: list[Issue]) -> str:
    for context in ctx.neighbours:
        c = context.strip()
        if not c:
            continue
        if new.startswith(c) or new.rstrip().endswith(c):
            trimmed = new[len(c) :] if new.startswith(c) else new.rstrip()[: -len(c)]
            if trimmed.strip():
                issues.append(Issue("echo", "fixed", "Text around the change, repeated, removed."))
                new = trimmed.strip("\n")
                continue
        mine, theirs = _shingles(new), _shingles(c)
        if theirs and len(mine & theirs) / len(theirs) >= ECHO_SHARE:
            issues.append(Issue("echo", "warn", "It repeats the text around it."))
    return new


def _g9_script(ctx: GuardContext, old: str, new: str, issues: list[Issue]) -> None:
    if ctx.translate:
        return
    a, b = main_script(old), main_script(new)
    if a and b and a != b:
        issues.append(Issue("language", "warn", "The language of the text changed."))
