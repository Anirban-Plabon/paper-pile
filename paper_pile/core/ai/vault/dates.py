"""Date ranges for vault requests (PLAN_vault_agent §4.2). The model only labels what the
user said ("last week", "October", "2025"); the days are computed here from ``today``, so a
model never does calendar arithmetic. No clock: callers pass ``today``."""

import calendar
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

UNITS = ("day", "week", "month", "year")


@dataclass(frozen=True, slots=True)
class DayRange:
    start: date
    end: date  # included

    def holds(self, day: date) -> bool:
        return self.start <= day <= self.end

    def iso(self) -> tuple[str, str]:
        return self.start.isoformat(), self.end.isoformat()


def _iso(value: object) -> date | None:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def unit_range(unit: str, around: date) -> DayRange:
    """The calendar ``unit`` holding ``around`` (weeks start on Monday)."""
    if unit == "day":
        return DayRange(around, around)
    if unit == "week":
        start = around - timedelta(days=around.weekday())
        return DayRange(start, start + timedelta(days=6))
    if unit == "month":
        last = calendar.monthrange(around.year, around.month)[1]
        return DayRange(around.replace(day=1), around.replace(day=last))
    return DayRange(date(around.year, 1, 1), date(around.year, 12, 31))


def _shift(unit: str, day: date, n: int) -> date:
    """``day`` moved ``n`` units back (a month end clamps to the shorter month)."""
    if unit == "day":
        return day - timedelta(days=n)
    if unit == "week":
        return day - timedelta(weeks=n)
    months = n * (12 if unit == "year" else 1)
    y, m = divmod(day.year * 12 + day.month - 1 - months, 12)
    return date(y, m + 1, min(day.day, calendar.monthrange(y, m + 1)[1]))


def _calendar(spec: Mapping[str, Any], today: date) -> DayRange | None:
    """``{"year": 2025, "month": 10, "day": 3}``, any part left out; a month without a year is
    the latest such month that has started."""
    year, month, day = _int(spec.get("year")), _int(spec.get("month")), _int(spec.get("day"))
    if month is not None and not 1 <= month <= 12:
        return None
    if month is None and (year is None or day is not None):
        return None
    try:
        if year is None:
            assert month is not None
            year = today.year if (month, day or 1) <= (today.month, today.day) else today.year - 1
        if month is None:
            return unit_range("year", date(year, 1, 1))
        if day is None:
            return unit_range("month", date(year, month, 1))
        return unit_range("day", date(year, month, day))
    except ValueError:
        return None


def date_range(spec: object, today: date) -> DayRange | None:
    """A day range from the model's label of a date phrase; None when it is not one.

    - ``{"from": "2025-10-01", "to": "2025-10-31"}``: either end may be left out;
    - ``{"year": 2025, "month": 10, "day": 3}``: calendar parts (:func:`_calendar`);
    - ``{"this": "week"}``: the unit holding today;
    - ``{"last": "month"}``: the whole unit before this one (yesterday, last week…);
    - ``{"past": 10, "unit": "day"}``: a rolling window that ends today.
    """
    if not isinstance(spec, Mapping):
        return None
    if "from" in spec or "to" in spec:
        start, end = _iso(spec.get("from")), _iso(spec.get("to"))
        if start is None and end is None:
            return None
        found = DayRange(start or date(1, 1, 1), end or today)
        return found if found.start <= found.end else None
    this, last = spec.get("this"), spec.get("last")
    if this in UNITS:
        return unit_range(str(this), today)
    if last in UNITS:
        return unit_range(str(last), _shift(str(last), today, 1))
    past, unit = _int(spec.get("past")), spec.get("unit", "day")
    if past is not None and past > 0 and unit in UNITS:
        return DayRange(_shift(str(unit), today, past) + timedelta(days=1), today)
    return _calendar(spec, today)
