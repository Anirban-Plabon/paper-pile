"""Daily notes and the calendar behind them (PLAN §4.15).

One note per day, named from a date format and kept in the daily-notes folder; created on demand
from an optional template note. Everything here is plain functions on dates and paths: no UI,
no clock (callers pass ``today`` / ``now``).
"""

import calendar
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from paper_pile.core.templates import render_template
from paper_pile.core.vault import NotFoundError, Vault, VaultError

DEFAULT_FORMAT = "YYYY-MM-DD"
# longest token first so MMMM is not read as MM MM; [text] is copied as written
_TOKENS = re.compile(r"\[([^\]]*)\]|YYYY|YY|MMMM|MMM|MM|M|DD|D|dddd|ddd|HH|mm|WW")
_OPEN_TASK = re.compile(r"^[ \t>]*[-*+][ \t]+\[ \]", re.MULTILINE)
_FORBIDDEN = re.compile(r'[\\:*?"<>|\x00-\x1f]')


def format_date(value: date | datetime, fmt: str) -> str:
    """Format ``value`` with Moment-style tokens: YYYY YY MMMM MMM MM M DD D dddd ddd HH mm WW,
    and ``[literal]`` text."""

    def part(m: re.Match[str]) -> str:
        token = m.group(0)
        if m.group(1) is not None:
            return m.group(1)
        hour = value.hour if isinstance(value, datetime) else 0
        minute = value.minute if isinstance(value, datetime) else 0
        return {
            "YYYY": f"{value.year:04d}",
            "YY": f"{value.year % 100:02d}",
            "MMMM": value.strftime("%B"),
            "MMM": value.strftime("%b"),
            "MM": f"{value.month:02d}",
            "M": str(value.month),
            "DD": f"{value.day:02d}",
            "D": str(value.day),
            "dddd": value.strftime("%A"),
            "ddd": value.strftime("%a"),
            "HH": f"{hour:02d}",
            "mm": f"{minute:02d}",
            "WW": f"{value.isocalendar().week:02d}",
        }[token]

    return _TOKENS.sub(part, fmt)


def format_problem(fmt: str) -> str:
    """Why ``fmt`` cannot name daily notes ("" if it can)."""
    probe = format_date(date(2026, 10, 1), fmt.strip())
    if not fmt.strip():
        return "A date format is needed"
    if probe.startswith("/") or any(
        p in {"", ".", ".."} or p.startswith(".") for p in probe.split("/")
    ):
        return "Cannot name a note or folder this way"
    if _FORBIDDEN.search(probe):
        return "Contains characters a file name cannot have"
    if format_date(date(2026, 10, 2), fmt) == probe:
        return "Must include the day (for example YYYY-MM-DD)"
    return ""


def daily_relpath(day: date, folder: str, fmt: str = DEFAULT_FORMAT) -> str:
    """Vault path of the note for ``day``."""
    name = format_date(day, fmt or DEFAULT_FORMAT) + ".md"
    folder = folder.strip("/")
    return f"{folder}/{name}" if folder else name


@dataclass(frozen=True, slots=True)
class Day:
    date: date
    in_month: bool
    is_today: bool


@dataclass(frozen=True, slots=True)
class Week:
    number: int  # ISO week number
    days: tuple[Day, ...]


def month_grid(year: int, month: int, today: date) -> list[Week]:
    """The six Monday-first weeks that show ``month``, with the days around it filled in."""
    first = date(year, month, 1)
    start = first - timedelta(days=first.weekday())
    weeks: list[Week] = []
    for w in range(6):
        monday = start + timedelta(weeks=w)
        days = tuple(
            Day(d, d.month == month and d.year == year, d == today)
            for d in (monday + timedelta(days=i) for i in range(7))
        )
        weeks.append(Week(monday.isocalendar().week, days))
    return weeks


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_name(month: int) -> str:
    return calendar.month_abbr[month]


@dataclass(frozen=True, slots=True)
class Marks:
    exists: bool = False
    open_tasks: bool = False


def day_marks(vault: Vault, folder: str, fmt: str, days: Iterable[date]) -> dict[date, Marks]:
    """Which of ``days`` have a daily note, and whether it still has unchecked tasks."""
    out: dict[date, Marks] = {}
    for day in days:
        path = daily_relpath(day, folder, fmt)
        try:
            text = vault.read_text(path)
        except (NotFoundError, VaultError):
            continue
        out[day] = Marks(True, bool(_OPEN_TASK.search(text)))
    return out


def new_daily_text(vault: Vault, template: str, day: date, now: datetime, fmt: str) -> str:
    """The starting text of a day's note: the template (placeholders filled for that day), or a
    heading with the date when there is no usable template."""
    title = format_date(day, fmt or DEFAULT_FORMAT).rsplit("/", 1)[-1]
    if template.strip():
        try:
            return render_template(vault.read_text(template), title=title, now=now, day=day)
        except VaultError:
            pass
    return f"# {title}\n\n"
