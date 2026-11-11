"""An AI change shown in the note while the AI writes it (user 2026-11-10): what it replaces in
red (−) at once, the new text growing in green (+) under it, the AI chip under that
(``tools/editor_src/proposal.js``, a *live* proposal). The real proposal — or nothing — replaces
it when the AI is done.

Fed by :attr:`EditRun.live <paper_pile.core.ai.edit_run.EditRun.live>`: :meth:`LiveEdit.changed`
only marks it changed; a loop sends at most every ``every`` seconds — the whole proposal when
the places changed, else only the new texts (the editor keeps the positions, which follow any
typing meanwhile).
"""

import asyncio
import logging
from collections.abc import Sequence

from nicegui import background_tasks

from paper_pile.core.ai.write import LiveChange
from paper_pile.core.textpos import utf16_index
from paper_pile.gui.components.editor import Editor

log = logging.getLogger("paper_pile.gui.live_edit")


class LiveEdit:
    def __init__(self, editor: Editor, doc_id: int, note: str, every: float) -> None:
        self._editor = editor
        self._doc_id = doc_id
        self._note = note  # the text the run's positions are in
        self._every = every
        self._live: list[LiveChange] = []
        self._dirty = False
        self._shape: tuple[tuple[int, int, bool], ...] | None = None
        self._task: asyncio.Task[None] | None = None
        self._shown = False

    def start(self) -> None:
        self._task = background_tasks.create(self._loop())

    def changed(self, live: Sequence[LiveChange]) -> None:
        self._live = list(live)
        self._dirty = True

    async def stop(self) -> None:
        """The run ended: the live changes go (the caller shows the result)."""
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._shown:
            self._shown = False
            await self._editor.show_proposal(self._doc_id, None)

    async def _loop(self) -> None:
        while True:
            if self._dirty:
                self._dirty = False
                try:
                    await self._send()
                except Exception:  # the preview must never stop the edit
                    log.exception("the live change could not be shown")
            await asyncio.sleep(self._every)

    async def _send(self) -> None:
        live = self._live
        shape = tuple((c.start, c.end, c.writing) for c in live)
        if shape == self._shape and self._shown:
            await self._editor.show_live_text(self._doc_id, [c.text for c in live])
            return
        self._shape = shape
        if not live:
            if self._shown:
                self._shown = False
                await self._editor.show_proposal(self._doc_id, None)
            return
        note = self._note
        hunks = [
            {
                "id": f"live{i}",
                "from": utf16_index(note, c.start),
                "to": utf16_index(note, c.end),
                "insert": c.text,
                "after": c.after,
                "writing": c.writing,
            }
            for i, c in enumerate(live)
        ]
        self._shown = await self._editor.show_proposal(
            self._doc_id, {"id": "live", "live": True, "hunks": hunks}
        )
