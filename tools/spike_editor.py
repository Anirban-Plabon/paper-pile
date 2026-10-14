"""Spike S1 demo page: exercises every editor capability. Not part of the shipped app.

Run: uv run python tools/spike_editor.py   (then open http://127.0.0.1:8099)
"""

import tempfile
from pathlib import Path

from fastapi import Request
from nicegui import app, ui

from paper_pile.gui.components.editor import Editor

STATIC = Path(__file__).resolve().parent.parent / "paper_pile" / "gui" / "static"
UPLOADS = Path(tempfile.mkdtemp(prefix="pp-spike-"))
SAMPLE = """# Spike S1/S2

Some **bold**, some *italic*, `inline code`, and ~~strike~~.

## Math

Euler: $e^{i\\pi}+1=0$ renders; "$5 and $10" stays text.

$$
\\int_0^\\infty e^{-x^2}\\,dx = \\frac{\\sqrt{\\pi}}{2}
$$

$$x^2 + y^2 = z^2$$

## Diagrams

```mermaid
flowchart LR
  A[Note] --> B{Link?}
  B -->|yes| C[Backlink]
  B -->|no| D[Orphan]
```

```mermaid
flowchart LR
  this is not valid ((
```

Type / at line start or after a space to fire the slash hook.
"""

app.add_static_files("/pp-static", STATIC)


@app.post("/_pp/paste-image")
async def paste_image(request: Request) -> dict[str, object]:
    body = await request.body()
    (UPLOADS / "last-paste.bin").write_bytes(body)
    return {"size": len(body)}


@ui.page("/")
def index() -> None:
    ui.add_head_html('<link rel="stylesheet" href="/pp-static/vendor/katex/katex.min.css">')
    ui.add_head_html('<link rel="stylesheet" href="/pp-static/app.css">')
    log = ui.log(max_lines=200).classes("w-full h-48")

    def show(name: str):  # type: ignore[no-untyped-def]
        def handler(e):  # type: ignore[no-untyped-def]
            args = e.args if isinstance(e.args, dict) else {"args": e.args}
            shown = {
                k: (v if not isinstance(v, str) or len(v) < 80 else v[:77] + "...")
                for k, v in args.items()
            }
            log.push(f"{name}: {shown}")

        return handler

    def on_paste(e):  # type: ignore[no-untyped-def]
        show("paste")(e)
        if e.args.get("kind") in ("html", "text"):
            editor.insert_at_cursor(e.args.get("text", ""))

    editor = (
        Editor(
            SAMPLE,
            image_upload_url="/_pp/paste-image",
            on_change=show("change"),
            on_slash=show("slash"),
            on_paste=on_paste,
        )
        .classes("w-full")
        .style("height: 520px; border: 1px solid #8884")
    )

    async def get() -> None:
        log.push(f"get_text: {len(await editor.get_text() or '')} chars")

    with ui.row():
        ui.button("Set text", on_click=lambda: editor.set_text("# Replaced from Python\n\n**ok**"))
        ui.button("Insert at cursor", on_click=lambda: editor.insert_at_cursor("hello"))
        ui.button("Get text", on_click=get)
        ui.button("Live", on_click=lambda: editor.set_mode("live"))
        ui.button("Source", on_click=lambda: editor.set_mode("source"))
        ui.button("Light", on_click=lambda: editor.set_theme("light"))
        ui.button("Dark", on_click=lambda: editor.set_theme("dark"))


ui.run(host="127.0.0.1", port=8099, reload=False, show=False, title="S1 spike")
