from paper_pile.core.ai.engine import PASTED
from paper_pile.gui.components.chat import _chip_text


def test_a_large_paste_reads_pasted_and_its_size() -> None:
    assert _chip_text("", PASTED, "40 lines") == "Pasted: [40 lines]"


def test_a_selection_chip_is_unchanged() -> None:
    text = _chip_text("qa", "Selected text", "60 chars")
    assert text.endswith(": [Selected text · 60 chars]") and "qa" in text
