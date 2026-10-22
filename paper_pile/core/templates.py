"""Note templates: a note in the templates folder, inserted at the caret (``/template``). The
templates themselves are written, added from a file and listed here for Settings → Templates.

``{{date}}``, ``{{time}}`` and ``{{title}}`` are replaced; so are ``{{date:FORMAT}}`` and
``{{time:FORMAT}}`` (Moment-style tokens, see :func:`paper_pile.core.daily.format_date`). Anything
else is left as written. For a daily note ``day`` is that day instead of today.
"""

import re
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paper_pile.core.ai.provider import ChatMessage
    from paper_pile.core.vault import Vault

DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"
_FORMATTED = re.compile(r"\{\{(date|time):([^{}]+)\}\}")


def render_template(text: str, *, title: str, now: datetime, day: date | None = None) -> str:
    from paper_pile.core.daily import format_date  # daily imports this module

    when = datetime.combine(day, now.time()) if day is not None else now

    def formatted(m: re.Match[str]) -> str:
        return format_date(when, m.group(2))

    return (
        _FORMATTED.sub(formatted, text)
        .replace("{{date}}", when.strftime(DATE_FORMAT))
        .replace("{{time}}", now.strftime(TIME_FORMAT))
        .replace("{{title}}", title)
    )


# ---- the templates folder (Settings → General → Templates) -------------------------------------


def list_templates(vault: "Vault", folder: str) -> list[str]:
    """The notes in the templates folder (all levels), sorted by path; [] without a folder."""
    clean = folder.strip().strip("/")
    if not clean or not vault.exists(clean):
        return []
    prefix = clean + "/"
    return sorted((p for p in vault.walk_notes() if p.startswith(prefix)), key=str.lower)


def new_template(vault: "Vault", folder: str, name: str, text: str) -> str:
    """Create ``<folder>/<name>.md``; fails (``ExistsError``) if a template has that name."""
    from paper_pile.core.vault import join_rel, note_filename

    clean = folder.strip().strip("/")
    if not clean:
        raise ValueError("no templates folder")
    return vault.create_note(join_rel(clean, note_filename(name)), text)


def import_template(vault: "Vault", folder: str, source: Path) -> str:
    """Copy the text of ``source`` (any .md / .txt file) into the templates folder under its own
    name (``Name 1``, ``Name 2`` … when taken). Returns the new template's path."""
    text = source.read_text(encoding="utf-8", errors="replace")
    clean = folder.strip().strip("/")
    name = source.stem
    if vault.exists(f"{clean}/{name}.md"):
        name = vault.free_numbered_name(clean, name, ".md")
    return new_template(vault, clean, name, text)


def template_draft_messages(brief: str, language: str = "") -> list["ChatMessage"]:
    """Ask the model for a note template that does what ``brief`` describes."""
    from paper_pile.core.ai.provider import ChatMessage

    lang = f" Write it in {language}." if language else ""
    return [
        ChatMessage(
            "system",
            "You write markdown note templates for a note app. Reply with only the template: "
            "headings, short prompts and empty list items to fill in, no introduction and no "
            "code block around it. You may use {{title}}, {{date}} and {{time}}, which are "
            f"filled in when the template is used. Keep it under 40 lines.{lang}",
        ),
        ChatMessage("user", f"A template for: {brief.strip()}"),
    ]
