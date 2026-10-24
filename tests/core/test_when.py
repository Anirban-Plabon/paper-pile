import time

from paper_pile.core.when import edited_when


def _ts(y: int, mo: int, d: int, h: int = 12, mi: int = 0) -> float:
    return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))


def test_edited_when() -> None:
    now = _ts(2026, 3, 1, 18)
    assert edited_when(_ts(2026, 3, 1, 9, 5), now) == "today 09:05"
    assert edited_when(_ts(2026, 2, 28, 23, 59), now) == "yesterday 23:59"  # across a month end
    assert edited_when(_ts(2026, 1, 7, 14, 30), now) == "Jan 7 14:30"
    assert edited_when(_ts(2025, 10, 12), now) == "Oct 12, 2025"
    assert edited_when(_ts(2025, 12, 31, 8), _ts(2026, 1, 1)) == "yesterday 08:00"  # year end
