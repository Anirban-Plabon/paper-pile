"""The formatting menu's catalogue (core/format_items.py)."""

import json
from pathlib import Path

from paper_pile.core.config import DEFAULTS
from paper_pile.core.format_items import (
    BY_ID,
    DEFAULT_PINNED,
    ITEMS,
    MAX_PINNED,
    grouped,
    pinned_items,
    toggle_pinned,
)
from paper_pile.core.formatting import INLINE, LINE_KINDS

ICONS = Path(__file__).parent.parent.parent / "paper_pile/gui/static/vendor/lucide/icons.json"


def test_defaults_are_the_users_five() -> None:
    assert DEFAULT_PINNED == ("highlight", "comment", "underline", "color", "link")
    assert DEFAULTS["editor"]["format_pinned"] == list(DEFAULT_PINNED)


def test_pinned_items_cleans_the_setting() -> None:
    assert pinned_items(None) == list(DEFAULT_PINNED)
    assert pinned_items("bold") == list(DEFAULT_PINNED)
    assert pinned_items(["bold", "nope", "bold", 3, "quote"]) == ["bold", "quote"]
    assert pinned_items([]) == []
    assert len(pinned_items([i.id for i in ITEMS])) == MAX_PINNED


def test_toggle_pinned() -> None:
    assert toggle_pinned(["bold"], "italic") == ["bold", "italic"]
    assert toggle_pinned(["bold", "italic"], "bold") == ["italic"]
    full = [i.id for i in ITEMS][:MAX_PINNED]
    assert toggle_pinned(full, ITEMS[-1].id) == full  # no room
    assert toggle_pinned(["bold"], "sparkle") == ["bold"]


def test_grouped_keeps_menu_order_and_skips() -> None:
    groups = grouped(exclude=["bold"])
    assert [g for g, _ in groups] == ["Text", "Blocks", "Alignment", "Edit"]
    assert all(i.id != "bold" for _, items in groups for i in items)


def test_every_text_item_is_known_to_formatting() -> None:
    known = set(INLINE) | set(LINE_KINDS) | {"color", "link", "comment"}
    for item in ITEMS:
        if item.group in ("Text", "Blocks"):
            assert item.id in known, item.id
    assert len(BY_ID) == len(ITEMS)


def test_every_icon_exists() -> None:
    icons = json.loads(ICONS.read_text(encoding="utf-8"))["icons"]
    for item in ITEMS:
        assert item.icon in icons, item.icon
