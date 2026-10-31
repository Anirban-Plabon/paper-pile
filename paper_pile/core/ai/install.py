"""Can the AI part run? Only when the app was started with ``paper-pile --ai`` (env
``PAPER_PILE_AI``); otherwise the app runs with AI off and says why (PLAN §4.26). No backend
library is needed: every provider talks HTTP (PLAN §4.30), so which backend and whether it is
reachable is the provider's health, not this.

``PAPER_PILE_NO_AI=1`` forces it off (tests, QA); ``PAPER_PILE_FAKE_AI=1`` needs no ``--ai``, so
it counts as available.
"""

import os
from functools import cache

START_HINT = "paper-pile --ai"
NOT_STARTED = f"AI is off — start the app with: {START_HINT}"


@cache
def ai_unavailable() -> str:
    """Why the AI cannot run ("" when it can)."""
    if os.environ.get("PAPER_PILE_NO_AI"):
        return NOT_STARTED
    if os.environ.get("PAPER_PILE_FAKE_AI"):
        return ""
    return "" if os.environ.get("PAPER_PILE_AI") else NOT_STARTED


def ai_available() -> bool:
    return not ai_unavailable()
