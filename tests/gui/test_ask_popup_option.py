"""The Ask box under a selection (PLAN §4.27) follows AI and its own switch."""

from pathlib import Path

from paper_pile.core.config import Config
from paper_pile.gui.theme import EDITOR_OPTION_KEYS, editor_options


def test_the_box_needs_ai_and_its_switch(tmp_path: Path) -> None:
    config = Config(vault=tmp_path)
    assert editor_options(config)["aiPopup"] is True
    config.set("ai.selection_popup", False, "global")
    assert editor_options(config)["aiPopup"] is False
    config.set("ai.selection_popup", True, "global")
    config.set("features.ai", False, "global")
    assert editor_options(config)["aiPopup"] is False
    assert {"ai.selection_popup", "features.ai"} <= EDITOR_OPTION_KEYS  # applied live
