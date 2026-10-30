"""Answer commands on a note too long for the context window (``docs/AI_EDITS.md`` §5): the
map step. Each part (``chunks``: a section where it can be) is condensed to a short summary in
its own call; the answer is then written from those summaries, which fit. More than
:data:`MAX_PARTS` parts: the first ones, and the model is told so. No UI imports.
"""

from collections.abc import Callable

from paper_pile.core.ai.blocks import block_map
from paper_pile.core.ai.commands import AiCommand
from paper_pile.core.ai.context import estimate_tokens
from paper_pile.core.ai.edit_context import chunk_tokens, chunks
from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.provider import ChatMessage

MAX_PARTS = 8
PART_WORDS = 120


def part_messages(cmd: AiCommand, part: str, n: int, total: int) -> list[ChatMessage]:
    """The task for one part: what matters in it for ``cmd`` (Summarize, Explain, Outline)."""
    rules = (
        f"You read part {n} of {total} of a long markdown note for the command “{cmd.title}”. "
        f"Write what matters in this part for it, in at most {PART_WORDS} words, in the "
        "language of the text. Keep names, numbers and decisions. Reply with only that text."
    )
    return [ChatMessage("system", rules), ChatMessage("user", f"Part {n}:\n<<<\n{part}\n>>>")]


async def condensed(
    engine: AiEngine,
    cmd: AiCommand,
    text: str,
    on_progress: Callable[[int, int], None] = lambda n, total: None,
) -> str | None:
    """``text`` as short summaries of its parts when it is too long for one call, else None
    (it fits: the answer is written from the text itself)."""
    limit = chunk_tokens(await engine.window())
    if estimate_tokens(text) <= limit:
        return None
    parts = chunks(block_map(text), text, limit)
    shown = parts[:MAX_PARTS]
    out: list[str] = []
    for n, part in enumerate(shown, 1):
        on_progress(n, len(shown))
        piece = text[part[0].start : part[-1].end]
        messages = part_messages(cmd, piece, n, len(parts))
        words = [p async for p in engine.stream(messages, think=False, max_answer=PART_WORDS * 3)]
        out.append(f"Part {n}:\n" + "".join(words).strip())
    head = (
        f"(A long note: the first {len(shown)} of {len(parts)} parts, each condensed.)\n\n"
        if len(parts) > len(shown)
        else "(A long note: each part condensed.)\n\n"
    )
    return head + "\n\n".join(out)
