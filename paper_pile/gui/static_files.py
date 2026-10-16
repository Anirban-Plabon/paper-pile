"""Where our own CSS/JS is served from, with cache-busting URLs."""

from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"
STATIC_URL = "/pp-static"


def static_url(name: str) -> str:
    """URL of one of our static files, with its mtime so an edited file is never served stale."""
    return f"{STATIC_URL}/{name}?v={int((STATIC_DIR / name).stat().st_mtime)}"
