"""A short local "when" for a file time, as shown in a note's properties ("Last edited")."""

import time


def edited_when(ts: float, now: float) -> str:
    """``today 14:05``, ``yesterday 09:12``, ``Oct 12 14:05`` (this year) or ``Oct 12, 2025``."""
    day, today = time.localtime(ts), time.localtime(now)
    clock = time.strftime("%H:%M", day)
    if (day.tm_year, day.tm_yday) == (today.tm_year, today.tm_yday):
        return f"today {clock}"
    yesterday = time.localtime(time.mktime((*today[:2], today.tm_mday - 1, *today[3:6], 0, 0, -1)))
    if (day.tm_year, day.tm_yday) == (yesterday.tm_year, yesterday.tm_yday):
        return f"yesterday {clock}"
    if day.tm_year == today.tm_year:
        return time.strftime("%b %d ", day).replace(" 0", " ") + clock
    return time.strftime("%b %d, %Y", day).replace(" 0", " ")
