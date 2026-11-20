"""Pieces of a note an AI edit must keep exactly (PLAN §4.29, ``docs/AI_EDITS.md`` §4.5–4.6).

*Inline tokens* — wikilinks, embeds, images, link targets, URLs, inline code and math, tags,
footnote references, block ids, HTML — are listed for the prompt ("Keep exactly: …") and checked
in the answer (guard G3); they are not masked, because their words carry meaning the model needs.
*Fixed blocks* inside a changed region — fenced code, ``$$`` math, diagrams — are replaced by
``⟦KEEP n⟧`` lines before sending and put back after (guard G4), so they come back byte for byte.
*Comments* (``%%…%%``, PLAN §4.38) are notes to self, not text to rewrite: they are lifted out
before sending and put back after the same words (:func:`lift_comments`, :func:`restore_comments`),
so a rewrite can neither lose nor reword them. ``//`` comments are visible text: kept exactly.
Pure; no UI imports.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

# in order: a token found by an earlier pattern is not found again by a later one
_PATTERNS = (
    re.compile(r"`[^`\n]+`"),
    re.compile(r"<!--.*?-->", re.DOTALL),
    re.compile(r"!?\[\[[^\]\n]+\]\]"),
    re.compile(r"!\[[^\]\n]*\]\([^)\s]+(?:\s+\"[^\"]*\")?\)"),
    re.compile(r"(?<=\]\()[^)\s]+(?=(?:\s+\"[^\"]*\")?\))"),  # a link's target, not its text
    re.compile(r"(?<!\$)\$(?!\$)[^$\n]+?(?<!\s)\$(?!\$)"),
    re.compile(r"https?://[^\s)>\]]*[^\s)>\].,;:!?'\"]"),
    re.compile(r"(?:^|(?<=[ \t]))//[^\n]*", re.MULTILINE),  # a `//` comment (after the URLs)
    re.compile(r"\[\^[^\]\n]+\]"),
    re.compile(r"(?<![\w/#&])#[\w/-]*[^\W\d_][\w/-]*"),
    re.compile(r"(?<=\s)\^[\w-]+$", re.MULTILINE),
    re.compile(r"</?[a-zA-Z][^>\n]*>"),
)
KEEP = "⟦KEEP {n}⟧"
_KEEP_LINE = re.compile(r"^[ \t]*⟦KEEP (\d+)⟧[ \t]*$", re.MULTILINE)


def protected_tokens(text: str) -> list[str]:
    """The inline tokens of ``text``, in order (a token twice is listed twice)."""
    found: list[tuple[int, str]] = []
    rest = text
    for pattern in _PATTERNS:
        for m in pattern.finditer(rest):
            found.append((m.start(), m.group(0)))
        rest = pattern.sub(lambda m: " " * len(m.group(0)), rest)
    return [token for _, token in sorted(found)]


def missing_tokens(old: str, new: str, allowed: Sequence[str] = ()) -> list[str]:
    """Tokens of ``old`` that ``new`` lost (each as often as it is missing), except ``allowed``
    ones (the user asked to remove them)."""
    lost = Counter(protected_tokens(old)) - Counter(protected_tokens(new))
    return [t for t in lost.elements() if not any(a and a in t for a in allowed)]


def mask(text: str, spans: Sequence[tuple[int, int]]) -> tuple[str, list[str]]:
    """``text`` with each ``spans`` range (a fixed block, offsets into ``text``) replaced by a
    ``⟦KEEP n⟧`` line; the kept texts, in order."""
    kept: list[str] = []
    out: list[str] = []
    at = 0
    for start, end in sorted(spans):
        out.append(text[at:start])
        out.append(KEEP.format(n=len(kept) + 1))
        kept.append(text[start:end])
        at = end
    out.append(text[at:])
    return "".join(out), kept


def unmask(text: str, kept: Sequence[str]) -> tuple[str, list[int]]:
    """``text`` with its ``⟦KEEP n⟧`` lines put back; the numbers that are missing or appear
    more than once (those blocks are not safe: the change must not be made)."""
    seen = Counter(int(m.group(1)) for m in _KEEP_LINE.finditer(text))
    bad = [n for n in range(1, len(kept) + 1) if seen[n] != 1]
    bad += [n for n in seen if not 1 <= n <= len(kept)]

    def back(m: re.Match[str]) -> str:
        n = int(m.group(1))
        return kept[n - 1] if 1 <= n <= len(kept) else m.group(0)

    return _KEEP_LINE.sub(back, text), sorted(set(bad))


# ---- comments (PLAN §4.38) ----------------------------------------------------------------------

_COMMENT = re.compile(r"%%(?:[^\n%]|%(?!%))*%%")
_LINE_COMMENT = re.compile(r"(?:^|(?<=[ \t]))//", re.MULTILINE)
ANCHOR_WORDS = 3


@dataclass(frozen=True, slots=True)
class Lifted:
    """A ``%%comment%%`` taken out of the text: the mark itself and the words right before it."""

    mark: str
    anchor: str  # up to ANCHOR_WORDS words before it ("" at the very start)


def lift_comments(text: str) -> tuple[str, tuple[Lifted, ...]]:
    """``text`` without its ``%%comments%%``, and the comments with where they were."""
    out: list[str] = []
    lifted: list[Lifted] = []
    pos = 0
    for m in _COMMENT.finditer(text):
        out.append(text[pos : m.start()])
        words = "".join(out).split()[-ANCHOR_WORDS:]
        lifted.append(Lifted(m.group(0), " ".join(words)))
        pos = m.end()
    out.append(text[pos:])
    return "".join(out), tuple(lifted)


def restore_comments(text: str, lifted: Sequence[Lifted]) -> str:
    """Put lifted comments back into a rewritten ``text``: each right after its words (the last
    three, else two, else one of them, searched after the comment put back before it); when the
    rewrite no longer has them, at the end, so a comment is never lost."""
    pos = 0
    for c in lifted:
        at: int | None = 0 if not c.anchor else None
        words = c.anchor.split()
        for k in range(len(words), 0, -1):
            m = re.compile(r"\s+".join(map(re.escape, words[-k:]))).search(text, pos)
            if m is not None:
                at = m.end()
                break
        if at is None:  # at the end, but before a `//` comment there (it would swallow it)
            text = text.rstrip()
            line_start = text.rfind("\n") + 1
            slash = _LINE_COMMENT.search(text, line_start)
            end = slash.start() if slash is not None else len(text)
            head = text[:end].rstrip()
            text = head + c.mark + (" " + text[end:] if slash is not None else "")
            pos = len(head) + len(c.mark)
            continue
        text = text[:at] + c.mark + text[at:]
        pos = at + len(c.mark)
    return text
