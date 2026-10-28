"""Can the AI part run? Only when the app was started with ``paper-pile --ai`` (env
``PAPER_PILE_AI``) and ``ollama`` can be imported; otherwise the app runs with AI off and says
why (PLAN §4.26). A separate install without ``ollama`` comes later.

``PAPER_PILE_NO_AI=1`` forces it off (tests, QA); ``PAPER_PILE_FAKE_AI=1`` needs no ``ollama``
and no ``--ai``, so it counts as available.
"""

import importlib.util
import os
from functools import cache

START_HINT = "paper-pile --ai"
INSTALL_HINT = "uv sync"
NOT_STARTED = f"AI is off — start the app with: {START_HINT}"
NOT_INSTALLED = f"AI is not installed — run: {INSTALL_HINT}"


@cache
def ai_unavailable() -> str:
    """Why the AI cannot run ("" when it can)."""
    if os.environ.get("PAPER_PILE_NO_AI"):
        return NOT_STARTED
    if os.environ.get("PAPER_PILE_FAKE_AI"):
        return ""
    if not os.environ.get("PAPER_PILE_AI"):
        return NOT_STARTED
    return "" if importlib.util.find_spec("ollama") is not None else NOT_INSTALLED


def ai_available() -> bool:
    return not ai_unavailable()
