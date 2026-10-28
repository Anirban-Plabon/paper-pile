"""Is the AI part installed? ``ollama`` comes with the ``ai`` extra (``uv sync --extra ai``);
without it the app runs with AI off and says how to add it (PLAN §4.26).

``PAPER_PILE_NO_AI=1`` acts as if it were missing (tests, QA); ``PAPER_PILE_FAKE_AI=1`` needs no
``ollama`` at all, so it counts as installed.
"""

import importlib.util
import os
from functools import cache

INSTALL_HINT = "uv sync --extra ai"
NOT_INSTALLED = f"AI is not installed — run: {INSTALL_HINT}"


@cache
def ai_installed() -> bool:
    if os.environ.get("PAPER_PILE_NO_AI"):
        return False
    if os.environ.get("PAPER_PILE_FAKE_AI"):
        return True
    return importlib.util.find_spec("ollama") is not None
