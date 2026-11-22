"""Keyboard shortcuts: one capture-phase listener, Python decides what each combo does.

Only combos that have a registered handler are intercepted (``preventDefault``); everything
else (Ctrl+C/V/Z, find, ...) reaches the editor untouched. Combos are normalised to
``[ctrl+][alt+][shift+]<key lower-case>``, e.g. ``ctrl+b``, ``ctrl+shift+f``, ``alt+w``.
Meta counts as Ctrl. Alt-only combos exist because web browsers reserve Ctrl+W/Ctrl+Tab.
Combos in ``editor_first`` go to the editor instead while it holds a selection (Ctrl+B bolds the
selected words, else folds the left pane; ``window.ppEditorHasSelection``, editor bundle).
Verified in the native Qt window in S3.
"""

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from nicegui import ui

log = logging.getLogger("paper_pile.shortcuts")

_JS = """
(function (registered, editorFirst) {
  window.addEventListener('keydown', function (e) {
    if (!(e.ctrlKey || e.metaKey || e.altKey)) return;
    if (['Control', 'Shift', 'Meta', 'Alt'].includes(e.key)) return;
    var parts = [];
    if (e.ctrlKey || e.metaKey) parts.push('ctrl');
    if (e.altKey) parts.push('alt');
    if (e.shiftKey) parts.push('shift');
    parts.push(e.key.toLowerCase());
    var combo = parts.join('+');
    if (!registered.has(combo)) return;
    var toEditor = window.ppEditorHasSelection;
    if (editorFirst.has(combo) && toEditor && toEditor(e.target)) return;
    e.preventDefault();
    e.stopPropagation();
    emitEvent('pp_shortcut', {combo: combo});
  }, true);
})(new Set(%s), new Set(%s));
"""


def install_shortcuts(
    handlers: Mapping[str, Callable[[], None]], editor_first: Iterable[str] = ()
) -> None:
    """Register ``handlers`` (combo -> callable) for the current page. Call inside a page."""
    combos = (json.dumps(sorted(handlers)), json.dumps(sorted(editor_first)))
    ui.add_body_html(f"<script>{_JS % combos}</script>")

    def dispatch(e: Any) -> None:
        handler = handlers.get(e.args.get("combo", ""))
        if handler is None:
            return
        try:
            handler()
        except Exception:
            log.exception("shortcut %s failed", e.args.get("combo"))

    ui.on("pp_shortcut", dispatch)
