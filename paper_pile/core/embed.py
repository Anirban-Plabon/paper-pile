"""``![[note]]``: another note shown inside this one (the 'embed note' command).

The editor asks for the embedded note's content (``/_pp/embed``); this module finds the note the
way a click on ``[[note]]`` would, optionally cuts out one section (``![[note#heading]]``) and
renders it to safe HTML (raw HTML in notes is escaped; remote images are never loaded).
"""

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

from paper_pile.core.links import resolve_wikilink
from paper_pile.core.parser import find_heading, headings, render_html
from paper_pile.core.vault import Vault, VaultError

MAX_CHARS = 30_000
_IMG = re.compile(r'<img src="([^"]*)" alt="([^"]*)"([^>]*)>')
_REMOTE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)")


@dataclass(frozen=True, slots=True)
class Embed:
    path: str | None  # the note shown, None if the link points at nothing
    title: str
    html: str
    message: str = ""  # why there is nothing to show (missing note / heading)


def section(text: str, heading: str) -> str | None:
    """The part of ``text`` under ``heading`` up to the next heading of the same or a higher level
    (the heading line itself included), or ``None`` if there is no such heading."""
    found = find_heading(text, heading)
    if found is None:
        return None
    lines = text.split("\n")
    end = len(lines)
    for other in headings(text):
        if other.line > found.line and other.level <= found.level:
            end = other.line - 1
            break
    return "\n".join(lines[found.line - 1 : end])


def _fix_images(html: str, note: str) -> str:
    """Images of the embedded note are served from ITS assets folder; remote ones are dropped."""

    def swap(m: re.Match[str]) -> str:
        src, alt = m.group(1), m.group(2)
        if _REMOTE.match(src):
            return f'<span class="pp-image-chip">{alt or "remote image"}</span>'
        url = f"/_pp/asset?note={quote(note, safe='')}&amp;path={quote(unquote(src), safe='')}"
        return f'<img src="{url}" alt="{alt}"{m.group(3)}>'

    return _IMG.sub(swap, html)


def embed(vault: Vault, source: str, target: str, heading: str = "") -> Embed:
    """What ``![[target#heading]]`` in the note ``source`` shows."""
    paths = list(vault.walk_notes())
    path = resolve_wikilink(target, source, paths)
    if path is None:
        return Embed(None, target, "", f"No note named “{target}”")
    try:
        text = vault.read_text(path)
    except VaultError:
        return Embed(None, target, "", f"Could not read {path}")
    title = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if heading:
        part = section(text, heading)
        if part is None:
            return Embed(path, title, "", f"No heading “{heading}” in {title}")
        text, title = part, f"{title} › {heading}"
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n\n…"
    return Embed(path, title, _fix_images(render_html(text), path))
