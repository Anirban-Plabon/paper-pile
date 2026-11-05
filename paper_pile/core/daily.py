"""Daily notes and the calendar behind them (PLAN §4.15).

One note per day, named from a date format and kept in the daily-notes folder; created on demand
from an optional template note. Everything here is plain functions on dates and paths: no UI,
no clock (callers pass ``today`` / ``now``).
"""

import calendar
import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from paper_pile.core.fsutil import atomic_write_bytes
from paper_pile.core.rewrite import Edit
from paper_pile.core.templates import render_template
from paper_pile.core.vault import NotFoundError, TreeEntry, Vault, VaultError

DEFAULT_FORMAT = "YYYY-MM-DD"
# longest token first so MMMM is not read as MM MM; [text] is copied as written
_TOKENS = re.compile(r"\[([^\]]*)\]|YYYY|YY|MMMM|MMM|MM|M|DD|D|dddd|ddd|HH|mm|WW")
_OPEN_TASK = re.compile(r"^[ \t>]*[-*+][ \t]+\[ \]", re.MULTILINE)
_FORBIDDEN = re.compile(r'[\\:*?"<>|\x00-\x1f]')
_FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(?:[^\n]*\n)*?---[ \t]*(?:\r?\n|\Z)")


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


_MONTHS = [calendar.month_name[i].casefold() for i in range(1, 13)]
_MONTHS_SHORT = [calendar.month_abbr[i].casefold() for i in range(1, 13)]
_NUM = {"YYYY": r"\d{4}", "YY": r"\d{2}", "MM": r"\d{2}", "M": r"\d{1,2}", "DD": r"\d{2}"}
_NUM |= {"D": r"\d{1,2}", "HH": r"\d{2}", "mm": r"\d{2}", "WW": r"\d{2}"}


def _name_pattern(fmt: str) -> tuple[re.Pattern[str], list[str]]:
    """A regex for the names ``fmt`` makes, and the token of each group."""
    out: list[str] = []
    tokens: list[str] = []
    at = 0
    for m in _TOKENS.finditer(fmt):
        out.append(re.escape(fmt[at : m.start()]))
        at = m.end()
        token = m.group(0)
        if m.group(1) is not None:
            out.append(re.escape(m.group(1)))
            continue
        tokens.append(token)
        out.append(f"({_NUM.get(token, r'[^/\d]+?')})")  # names (MMMM, dddd…): letters
    out.append(re.escape(fmt[at:]))
    return re.compile("".join(out), re.IGNORECASE), tokens


def daily_date(rel: str, folder: str, fmt: str = DEFAULT_FORMAT) -> date | None:
    """The day a note in the daily-notes folder is named for (``daily_relpath`` read back);
    ``None`` for a note outside the folder or not named by ``fmt``."""
    folder = folder.strip("/")
    if folder and not rel.startswith(folder + "/"):
        return None
    stem = rel[len(folder) + 1 :] if folder else rel
    stem = stem[:-3] if stem.lower().endswith(".md") else stem
    pattern, tokens = _name_pattern(fmt or DEFAULT_FORMAT)
    m = pattern.fullmatch(stem)
    if m is None:
        return None
    parts: dict[str, int] = {}
    for token, text in zip(tokens, m.groups(), strict=True):
        low = text.casefold()
        if token == "MMMM" and low in _MONTHS:
            parts["month"] = _MONTHS.index(low) + 1
        elif token == "MMM" and low in _MONTHS_SHORT:
            parts["month"] = _MONTHS_SHORT.index(low) + 1
        elif token in ("YYYY", "YY"):
            parts["year"] = int(text) + (2000 if token == "YY" else 0)
        elif token in ("MM", "M"):
            parts["month"] = int(text)
        elif token in ("DD", "D"):
            parts["day"] = int(text)
    try:
        day = date(parts["year"], parts["month"], parts["day"])
    except (KeyError, ValueError):
        return None
    return day if daily_relpath(day, folder, fmt or DEFAULT_FORMAT) == rel else None


def daily_order(
    entries: list[TreeEntry], folder: str, fmt: str, today: date
) -> tuple[list[TreeEntry], str | None]:
    """One tree level inside the daily-notes folder: folders first (as listed), then the dated
    notes newest first — future days above today, past days below — then the other notes (as
    listed). Also the note to show first: today's, else the latest day before it."""
    dated: list[tuple[date, TreeEntry]] = []
    rest: list[TreeEntry] = []
    for entry in entries:
        day = None if entry.is_dir else daily_date(entry.path, folder, fmt)
        if day is None:
            rest.append(entry)
        else:
            dated.append((day, entry))
    dated.sort(key=lambda d: d[0], reverse=True)
    first = next((e.path for d, e in dated if d <= today), None)
    folders = [e for e in rest if e.is_dir]
    notes = [e for e in rest if not e.is_dir]
    return folders + [e for _, e in dated] + notes, first


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


def day_marks(
    vault: Vault,
    folder: str,
    fmt: str,
    days: Iterable[date],
    cache: dict[str, tuple[float, bool]] | None = None,
) -> dict[date, Marks]:
    """Which of ``days`` have a daily note, and whether it still has unchecked tasks.

    Each folder is listed once and only existing notes are read (the calendar asks on every
    tab switch, ~42 days); ``cache`` (path → mtime, open tasks) spares re-reading notes that
    did not change since the last call.
    """
    by_folder: dict[str, list[tuple[date, str]]] = {}
    for day in days:
        path = daily_relpath(day, folder, fmt)
        by_folder.setdefault(path.rpartition("/")[0], []).append((day, path))
    out: dict[date, Marks] = {}
    for parent, wanted in by_folder.items():
        try:
            with os.scandir(vault.resolve(parent, allow_root=True)) as it:
                entries = {e.name: e for e in it}
        except (OSError, VaultError):
            continue
        folded = {name.casefold(): e for name, e in entries.items()}  # case-insensitive drives
        for day, path in wanted:
            name = path.rpartition("/")[2]
            entry = entries.get(name) or folded.get(name.casefold())
            if entry is None:
                continue
            try:
                mtime = entry.stat().st_mtime
                hit = cache.get(path) if cache is not None and not entry.is_symlink() else None
                if hit is not None and hit[0] == mtime:
                    open_tasks = hit[1]
                else:
                    open_tasks = bool(_OPEN_TASK.search(vault.read_text(path)))
                    if cache is not None:
                        cache[path] = (mtime, open_tasks)
            except (OSError, NotFoundError, VaultError):
                continue
            out[day] = Marks(True, open_tasks)
    return out


def new_daily_text(vault: Vault, template: str, day: date, now: datetime, fmt: str) -> str:
    """The starting text of a day's note: the template (placeholders filled for that day), or a
    heading with the date when there is no usable template."""
    title = daily_title(day, fmt)
    if template.strip():
        try:
            return render_template(vault.read_text(template), title=title, now=now, day=day)
        except VaultError:
            pass
    return f"# {title}\n\n"


def untouched_daily(
    text: str, vault: Vault, template: str, day: date, now: datetime, fmt: str
) -> bool:
    """Does a day's note still hold only what the app put there (the plain date heading, or the
    template as it renders now), with or without the ``title:`` property auto-title added? Such
    a note may be made again from the current template; anything the user wrote keeps it."""
    from paper_pile.core.titles import with_title  # titles imports the parser; keep this light

    name = daily_relpath(day, "", fmt or DEFAULT_FORMAT).rsplit("/", 1)[-1].rsplit(".", 1)[0]
    plain = f"# {format_date(day, fmt or DEFAULT_FORMAT).rsplit('/', 1)[-1]}\n\n"
    made = {plain, new_daily_text(vault, template, day, now, fmt)}
    made |= {t for t in (with_title(m, name) for m in made) if t is not None}
    clean = text.replace("\r\n", "\n").rstrip()
    return any(clean == m.rstrip() for m in made)


# ---- names follow the format setting (user, 2026-11-04) ------------------------------------
# When the date format changes, the daily notes already made are renamed to it, and the title the
# app gave them (the first heading, a ``title:`` property) follows. The format the notes were last
# named by is kept in ``.paper-pile/daily.json``; without that file the default format is assumed
# (every vault made before this used it unless the user changed it).

SYNC_FILE = "daily.json"


def daily_title(day: date, fmt: str) -> str:
    """The title a day's note is given: its date in ``fmt`` (the last part, for ``YYYY/MM/DD``)."""
    return format_date(day, fmt or DEFAULT_FORMAT).rsplit("/", 1)[-1]


# formats daily notes are often named by: a vault made before the app recorded its format
# (or with another app) is read by the one that names most of its notes (``daily_renames``)
COMMON_FORMATS = (
    "YYYY-MM-DD", "DD-MM-YYYY", "MM-DD-YYYY", "YYYY.MM.DD", "DD.MM.YYYY", "MM.DD.YYYY",
    "YYYY_MM_DD", "YYYYMMDD", "YYYY/MM/DD", "YYYY/MM/YYYY-MM-DD", "DD-MMM-YYYY", "DD MMM YYYY",
    "D MMMM YYYY", "MMMM D YYYY", "YYYY-MM-DD dddd", "dddd DD-MM-YYYY",
)  # fmt: skip


def synced_formats(root: Path) -> list[str]:
    """The formats the daily notes of the vault at ``root`` were named by, newest first
    ([] when never recorded)."""
    try:
        data = json.loads((root / ".paper-pile" / SYNC_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    found = data.get("formats")
    seen = [data.get("format")] + (found if isinstance(found, list) else [])
    return list(dict.fromkeys(f for f in seen if isinstance(f, str) and f.strip()))


def set_synced_format(root: Path, fmt: str) -> None:
    """Record ``fmt`` as the format the notes are now named by (kept with the earlier ones)."""
    formats = list(dict.fromkeys([fmt, *synced_formats(root)]))[:20]
    data = json.dumps({"format": fmt, "formats": formats}, indent=2).encode("utf-8")
    atomic_write_bytes(root / ".paper-pile" / SYNC_FILE, data)


@dataclass(frozen=True, slots=True)
class DailyRename:
    old: str
    new: str
    day: date
    old_fmt: str  # the format the old name was made by


def daily_renames(
    vault: Vault, folder: str, known: Iterable[str], new_fmt: str
) -> list[DailyRename]:
    """The notes in the daily-notes folder named by an earlier date format, with their name in
    ``new_fmt``. ``known`` are the formats the app named them by, newest first; a name none of
    them makes is read by the common format that fits most of the folder's notes (the current
    one wins a tie, so ``05-11-2026`` stays when it is a current name). Notes not named by a
    date are left alone."""
    folder = folder.strip("/")
    if not folder or format_problem(new_fmt):
        return []
    try:
        root = vault.resolve(folder)
    except VaultError:
        return []
    if not root.is_dir():
        return []
    rels = [
        f"{folder}/{path.relative_to(root).as_posix()}"
        for path in sorted(root.rglob("*.md"))
        if not path.is_symlink() and path.is_file()
    ]
    known = [f for f in dict.fromkeys(known) if not format_problem(f)]
    guesses = [f for f in dict.fromkeys([new_fmt, *COMMON_FORMATS]) if f not in known]
    fits = {f: sum(daily_date(r, folder, f) is not None for r in rels) for f in guesses}
    order = known + sorted((f for f in guesses if fits[f]), key=lambda f: -fits[f])
    out: list[DailyRename] = []
    for rel in rels:
        for fmt in order:
            day = daily_date(rel, folder, fmt)
            if day is None:
                continue
            new = daily_relpath(day, folder, new_fmt)
            if new != rel:
                out.append(DailyRename(rel, new, day, fmt))
            break
    return out


_TITLE_PROP = re.compile(r"^title:[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_HEADING = re.compile(r"^(#{1,6}[ \t]+)(.*?)[ \t#]*$", re.MULTILINE)


def retitle_daily(text: str, old_title: str, new_title: str) -> list[Edit]:
    """The edits that rename a day's note's title: the note's first heading and its ``title:``
    property, each only when it is still exactly the old date (the user's own titles stay)."""
    from paper_pile.core.titles import format_title  # titles imports the parser; keep it light

    edits: list[Edit] = []
    body = _FRONT_MATTER.match(text)
    start = body.end() if body else 0
    if body is not None:  # read as text: YAML would make a date of 2026-11-04
        line = _TITLE_PROP.search(text, 0, body.end())
        if line is not None and line.group(1).strip("'\"") == old_title:
            edits.append(Edit(line.start(1), line.end(1), format_title(new_title)))
    m = _HEADING.search(text, start)
    if m is not None and m.group(2).strip() == old_title:
        edits.append(Edit(m.start(2), m.end(2), new_title))
    return sorted(edits, key=lambda e: e.start)


def apply_edits(text: str, edits: list[Edit]) -> str:
    for e in sorted(edits, key=lambda e: e.start, reverse=True):
        text = text[: e.start] + e.insert + text[e.end :]
    return text
