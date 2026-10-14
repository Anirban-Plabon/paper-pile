"""Link extraction, resolution, and rewriting on rename/move.

So far: the policy for links that leave the app (P2.4). Note-to-note resolution, backlinks and
rename rewriting arrive with P3.
"""

import re
from urllib.parse import urlsplit

# Only these schemes may be opened from a note. Everything else (javascript:, file:, data:, ...)
# is refused, because a note can contain anything, including text pasted from a chatbot.
EXTERNAL_SCHEMES = frozenset({"http", "https", "mailto"})
_CONTROL = re.compile(r"[\x00-\x1f\x7f\s]")


def external_url(href: str) -> str | None:
    """The URL to open in the system browser for ``href``, or ``None`` if it must not be opened.

    ``www.example.org`` (a bare GFM autolink) gets ``https://``. Relative paths, note links and
    anything with an unsafe scheme return ``None``.
    """
    href = href.strip()
    if not href or _CONTROL.search(href):
        return None
    if href.lower().startswith("www."):
        href = "https://" + href
    parts = urlsplit(href)
    if parts.scheme.lower() not in EXTERNAL_SCHEMES:
        return None
    if parts.scheme.lower() in {"http", "https"} and not parts.netloc:
        return None
    return href
