"""``ui.dialog`` that cleans up after itself: use :class:`Dialog` for every dialog.

NiceGUI (3.16+) puts a hidden "canary" element where a dialog is created; the canary's
finalizer holds the dialog, and ``dialog.delete()`` leaves the canary behind. So every dialog
ever shown stayed in the page (an empty ``<div class="hidden">``) and its whole element tree on
the server (P20). :meth:`Dialog.delete` removes the canary too.
"""

from nicegui import context, ui
from nicegui.element import Element


class Dialog(ui.dialog):
    def __init__(self, *, value: bool = False) -> None:
        super().__init__(value=value)
        children = context.slot.children
        last = children[-1] if children else None
        self._canary = last if type(last) is Element and not last.visible else None

    def delete(self) -> None:
        canary, self._canary = self._canary, None
        super().delete()
        if canary is not None and not canary.is_deleted:
            canary.delete()
