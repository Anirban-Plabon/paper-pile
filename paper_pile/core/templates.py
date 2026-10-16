"""Note templates: a note in the templates folder, inserted at the caret.

``{{date}}``, ``{{time}}`` and ``{{title}}`` are replaced; so are ``{{date:FORMAT}}`` and
``{{time:FORMAT}}`` (Moment-style tokens, see :func:`paper_pile.core.daily.format_date`). Anything
else is left as written. For a daily note ``day`` is that day instead of today.
"""

import re
from datetime import date, datetime

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
