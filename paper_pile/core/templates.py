"""Note templates: a note in the templates folder, inserted at the caret.

``{{date}}``, ``{{time}}`` and ``{{title}}`` are replaced; anything else is left as written.
"""

from datetime import datetime

DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"


def render_template(text: str, *, title: str, now: datetime) -> str:
    return (
        text.replace("{{date}}", now.strftime(DATE_FORMAT))
        .replace("{{time}}", now.strftime(TIME_FORMAT))
        .replace("{{title}}", title)
    )
