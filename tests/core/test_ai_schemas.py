"""Every JSON schema the app sends to a model must be one every backend accepts (P30.51):
Gemini (through the Antigravity CLI) rejects an empty string in an ``enum`` with a 400, and the
vault agent then fell back to the plain chat on every request without a word."""

import importlib
import pkgutil
from typing import Any

import paper_pile.core.ai as ai_pkg


def _schemas() -> list[tuple[str, dict[str, Any]]]:
    found = []
    for mod in pkgutil.walk_packages(ai_pkg.__path__, "paper_pile.core.ai."):
        module = importlib.import_module(mod.name)
        for name, value in vars(module).items():
            if "SCHEMA" in name and isinstance(value, dict):
                found.append((f"{mod.name}.{name}", value))
    return found


def _bad_enums(node: object, where: str) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        enum = node.get("enum")
        if isinstance(enum, list) and any(v == "" for v in enum):
            out.append(where)
        for k, v in node.items():
            out += _bad_enums(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _bad_enums(v, f"{where}[{i}]")
    return out


def test_no_schema_has_an_empty_enum_value() -> None:
    schemas = _schemas()
    assert len(schemas) >= 8  # the scan finds them (vault understanding, loop, judge, …)
    bad = [w for name, schema in schemas for w in _bad_enums(schema, name)]
    assert bad == []
