"""Exporting a note as one self-contained file (the note menu's "Export as…").

- Markdown: the note's text with every local image inlined as a ``data:`` URI, so the one file
  carries its pictures.
- HTML: that markdown rendered (``parser.render_html``) inside a small page with its own
  stylesheet (light and dark). No scripts: math stays as TeX, diagrams as code.

Images that are not in the vault (web URLs) or cannot be read are left as they are.
"""

import base64
import mimetypes
from html import escape
from pathlib import Path

from paper_pile.core.assets import sniff_image
from paper_pile.core.parser import image_spans, render_html
from paper_pile.core.rewrite import Edit, apply_edits, locate_spans, scan_destination
from paper_pile.core.vault import Vault, VaultError

_MIME = {"jpg": "image/jpeg", "svg": "image/svg+xml"}


def data_uri(path: Path) -> str:
    data = path.read_bytes()
    kind = sniff_image(data)
    mime = _MIME.get(kind or "", f"image/{kind}") if kind else None
    mime = mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def inline_images(vault: Vault, note: str, text: str) -> str:
    """``text`` with each image stored in the vault replaced by a ``data:`` URI."""
    spans = image_spans(text)
    edits: list[Edit] = []
    for span, start in zip(spans, locate_spans(text, spans), strict=True):
        if start is None:
            continue
        found = scan_destination(span.source[1:])  # skip the "!"
        if found is None:
            continue
        d_start, d_end, _angle = found
        try:
            uri = data_uri(vault.asset_path(note, span.raw))
        except (VaultError, OSError):
            continue  # a web image, or one that is missing: keep the reference
        edits.append(Edit(start + 1 + d_start, start + 1 + d_end, uri))
    return apply_edits(text, edits) if edits else text


def export_markdown(vault: Vault, note: str, text: str) -> str:
    return inline_images(vault, note, text)


_STYLE = """
:root { color-scheme: light dark; --fg: #1f2328; --bg: #ffffff; --muted: #656d76;
  --border: #d0d7de; --code: #f3f4f6; --accent: #2563eb; }
@media (prefers-color-scheme: dark) { :root { --fg: #e6edf3; --bg: #0d1117; --muted: #8d96a0;
  --border: #30363d; --code: #161b22; --accent: #6ea8fe; } }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.65 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 48px 24px 96px; }
h1, h2, h3, h4 { line-height: 1.25; margin: 1.6em 0 .6em; }
a { color: var(--accent); }
img { max-width: 100%; height: auto; border-radius: 6px; }
code, pre { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .92em; }
code { background: var(--code); border-radius: 4px; padding: .1em .35em; }
pre { background: var(--code); border-radius: 8px; padding: 12px 14px; overflow-x: auto; }
pre code { background: none; padding: 0; }
blockquote { margin: 1em 0; padding: 0 1em; border-left: 3px solid var(--border);
  color: var(--muted); }
table { border-collapse: collapse; margin: 1em 0; }
th, td { border: 1px solid var(--border); padding: 6px 10px; }
hr { border: none; border-top: 1px solid var(--border); margin: 2em 0; }
.wikilink { color: var(--accent); }
.pp-page-break { break-after: page; page-break-after: always; }
@media screen { .pp-page-break { border-top: 1px dashed var(--border); margin: 2em 0; } }
"""


def export_html(vault: Vault, note: str, text: str, title: str) -> str:
    body = render_html(inline_images(vault, note, text))
    return (
        '<!doctype html>\n<html>\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(title)}</title>\n<style>{_STYLE}</style>\n</head>\n"
        f"<body>\n<main>\n{body}</main>\n</body>\n</html>\n"
    )
