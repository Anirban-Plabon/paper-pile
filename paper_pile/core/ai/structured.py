"""Answers the model gives as JSON (PLAN §4.29: the edit plan, the suggested options). The
backend constrains them to a schema, but small models still slip — text around the object, a
cut-off end — so the object is looked for leniently and anything else is None. No UI imports.
"""

import json
from typing import Any

_DECODER = json.JSONDecoder()


def parse_json_object(text: str) -> dict[str, Any] | None:
    """The JSON object in ``text``: all of it, else the first ``{…}`` that parses (a model that
    wrote words around it); None when there is none."""
    body = text.strip()
    try:
        whole = json.loads(body)
    except ValueError:
        whole = None
    if isinstance(whole, dict):
        return whole
    at = body.find("{")
    while at >= 0:
        try:
            found, _ = _DECODER.raw_decode(body, at)
        except ValueError:
            found = None
        if isinstance(found, dict):
            return found
        at = body.find("{", at + 1)
    return None
