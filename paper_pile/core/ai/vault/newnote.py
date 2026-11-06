"""A new note made from what was found (PLAN_vault_agent §3.2 ``write``, P30.32): the found
notes are summarised as the request asks (``summarise.py``, citations checked), the labels
become wikilinks to the source notes, and the note is offered as a new-note diff — written
only when the user applies it, under a free name (never over an existing note). No UI
imports.
"""

from collections.abc import Callable

from paper_pile.core.ai.engine import AiEngine
from paper_pile.core.ai.proposals import propose
from paper_pile.core.ai.vault.cards import CardMaker
from paper_pile.core.ai.vault.cite import to_wikilinks
from paper_pile.core.ai.vault.edits import EditBatch, NoteEdit, Target
from paper_pile.core.ai.vault.results import ResultSet
from paper_pile.core.ai.vault.summarise import summarise_many, summarise_note
from paper_pile.core.ai.vault.tools import VaultTools

_BAD = '\\/:*?"<>|#^[]'


def note_title(topic: str) -> str:
    """A file-safe title from the topic ("" → "Summary")."""
    clean = "".join(" " if c in _BAD else c for c in topic).strip()
    clean = " ".join(clean.split())[:80]
    return (clean[:1].upper() + clean[1:]) if clean else "Summary"


async def propose_new_note(
    engine: AiEngine,
    tools: VaultTools,
    maker: CardMaker,
    request: str,
    results: ResultSet,
    *,
    topic: str = "",
    folder: str = "",
    link: Callable[[str], str] = lambda p: p.rsplit("/", 1)[-1][:-3],
) -> EditBatch:
    items = results.sure() or results.maybe()
    title = note_title(topic)
    path = f"{folder.strip('/')}/{title}.md" if folder.strip("/") else f"{title}.md"
    batch = EditBatch(request, Target("add", "", request))
    if not items:
        batch.failed.append((title, "no notes to write it from"))
        return batch
    if len(items) == 1:
        reply = await summarise_note(engine, tools, items[0].path, request, results)
    else:
        reply = await summarise_many(engine, maker, request, results)
    if not reply.sources:
        batch.failed.append((title, reply.text))
        return batch
    body = to_wikilinks(reply.text, reply.sources, link)
    text = f"# {title}\n\n{body.strip()}\n"
    proposal = propose(path, "", 0, 0, text)
    if proposal is None:
        batch.failed.append((title, "nothing to write"))
        return batch
    batch.edits.append(NoteEdit(path, title, "", proposal, new=True))
    return batch
