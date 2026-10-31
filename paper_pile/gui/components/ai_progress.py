"""A running AI job (reading a long note, writing into it, planning an edit): a chip shaped like
the chat box at the bottom of the window — the AI icon in a circle, what the AI is doing, and
the chat's stop circle, rippling while the AI works; that circle is the Stop button (as the
chat's send button is while it answers). Replaces Quasar's notification with a spinner.

Used like that notification: ``message`` can be changed while it runs, :meth:`dismiss` removes
it. ``on_stop`` runs only when the user presses Stop (never on :meth:`dismiss`).
"""

from collections.abc import Callable

from nicegui import ui

from paper_pile.gui.components.right_pane import CHAT_ICON
from paper_pile.gui.icons import ico, line_icon
from paper_pile.gui.tips import tip


class AiProgress:
    def __init__(self, message: str, on_stop: Callable[[], None]) -> None:
        self._on_stop = on_stop
        with ui.row().classes("pp-aiprog pp-aiprog-chip items-center no-wrap") as root:
            self._root = root
            with ui.element("div").classes("pp-aiprog-ai"):
                line_icon(CHAT_ICON)
            self._label = ui.label(message).classes("pp-aiprog-text")
            with ui.element("div").classes("pp-aiprog-dot"):  # the ripple, behind the button
                self._stop = tip(
                    ui.button(icon=ico("square"), on_click=self._stopped, color=None)
                    .props("round unelevated dense aria-label=Stop")
                    .classes("pp-aiprog-stop"),
                    "Stop",
                )

    @property
    def message(self) -> str:
        return self._label.text

    @message.setter
    def message(self, text: str) -> None:
        if not self._label.is_deleted:
            self._label.set_text(text)

    def _stopped(self) -> None:
        self._stop.disable()
        self._root.classes("pp-aiprog-stopping")  # the ripple ends
        self.message = "Stopping…"
        self._on_stop()

    def dismiss(self) -> None:
        if not self._root.is_deleted:
            self._root.delete()
