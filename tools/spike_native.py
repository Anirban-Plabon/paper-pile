"""Spike S3: does the native window (pywebview[qt]) deliver app shortcuts to the page?

Run:  uv run python tools/spike_native.py            # native window
      PP_SPIKE_LOG=/tmp/keys.log ...                  # also append every key event to a file
The page captures Ctrl/Meta combos in the capture phase, preventDefault()s them and sends them
to Python. If the window itself closes or a combo never shows up, the shell swallowed it.
"""

import json
import os
from pathlib import Path

from nicegui import ui

LOG = os.environ.get("PP_SPIKE_LOG")

CAPTURE_JS = """
window.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  if (['Control', 'Shift', 'Meta', 'Alt'].includes(e.key)) return;
  e.preventDefault();
  emitEvent('pp_key', {key: e.key, ctrl: e.ctrlKey, shift: e.shiftKey, alt: e.altKey});
}, true);
"""


@ui.page("/")
def index() -> None:
    ui.add_body_html(f"<script>{CAPTURE_JS}</script>")
    ui.label("S3: press Ctrl+P, Ctrl+W, Ctrl+Tab, Ctrl+Shift+F ...").classes("text-lg")
    log = ui.log(max_lines=100).classes("w-full h-64")

    def on_key(e) -> None:  # type: ignore[no-untyped-def]
        line = json.dumps(e.args, sort_keys=True)
        log.push(line)
        if LOG:
            with Path(LOG).open("a") as f:
                f.write(line + "\n")

    ui.on("pp_key", on_key)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(native=True, reload=False, window_size=(900, 600), title="S3 spike", show=False)
