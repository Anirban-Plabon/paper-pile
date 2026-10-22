"""The Calendar tab: a month grid; a click opens (or creates) that day's daily note.

Monday-first with ISO week numbers. A filled dot under a day means its note exists, a hollow one
that the note still has unchecked tasks. The day of the note on screen is highlighted and today's
number uses the theme colour. What a day's note is called, where it lives and what it starts
from are Settings (General > Daily notes); the rules are in :mod:`paper_pile.core.daily`.
"""

from collections.abc import Callable
from datetime import date

from nicegui import ui

from paper_pile.core.config import Config
from paper_pile.core.daily import (
    DEFAULT_FORMAT,
    daily_relpath,
    day_marks,
    month_grid,
    month_name,
    shift_month,
)
from paper_pile.core.vault import Vault
from paper_pile.gui.icons import line_icon

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


class CalendarPane:
    def __init__(
        self,
        vault: Vault,
        config: Config,
        open_day: Callable[[date], None],
        active_path: Callable[[], str | None] = lambda: None,
        open_settings: Callable[[], None] = lambda: None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.vault = vault
        self.config = config
        self._open_day = open_day
        self._active_path = active_path
        self._open_settings = open_settings
        self._today = today
        t = today()
        self.year, self.month = t.year, t.month
        self._body: ui.column

    def build(self) -> None:
        """Call inside the host element."""
        self._body = ui.column().classes("pp-cal")
        self.refresh()

    # ---- navigation ----------------------------------------------------------------------

    def _step(self, delta: int) -> None:
        self.year, self.month = shift_month(self.year, self.month, delta)
        self.refresh()

    def _go_today(self) -> None:
        t = self._today()
        self.year, self.month = t.year, t.month
        self.refresh()

    # ---- drawing -------------------------------------------------------------------------

    def _settings(self) -> tuple[str, str]:
        folder = str(self.config.get("vault.daily_notes_folder", ""))
        fmt = str(self.config.get("vault.daily_notes_format", DEFAULT_FORMAT)) or DEFAULT_FORMAT
        return folder, fmt

    def refresh(self) -> None:
        """Redraw the month (dots and the highlighted day included)."""
        folder, fmt = self._settings()
        weeks = month_grid(self.year, self.month, self._today())
        marks = day_marks(self.vault, folder, fmt, (d.date for w in weeks for d in w.days))
        active = self._active_path()
        self._body.clear()
        with self._body:
            with ui.row().classes("pp-cal-head items-center no-wrap"):
                with ui.row().classes("pp-cal-title items-baseline no-wrap"):
                    ui.label(month_name(self.month)).classes("pp-cal-month")
                    ui.label(str(self.year)).classes("pp-cal-year")
                ui.space()
                prev = line_icon("chevron-left", "s").classes("pp-cal-nav")
                prev.on("click", lambda _e: self._step(-1))
                prev.props('data-tip="Previous month"')
                today = ui.label("TODAY").classes("pp-cal-today-btn")
                today.on("click", lambda _e: self._go_today())
                nxt = line_icon("chevron-right", "s").classes("pp-cal-nav")
                nxt.on("click", lambda _e: self._step(1))
                nxt.props('data-tip="Next month"')
            with ui.element("div").classes("pp-cal-grid"):
                ui.label("W").classes("pp-cal-wk pp-cal-colhead")
                for name in WEEKDAYS:
                    ui.label(name).classes("pp-cal-colhead")
                for week in weeks:
                    ui.label(str(week.number)).classes("pp-cal-wk")
                    for day in week.days:
                        self._day(day.date, day.in_month, day.is_today, marks, active, folder, fmt)
            note = f"in {folder}" if folder else "in the vault's top folder"
            with ui.row().classes("pp-cal-foot items-center no-wrap"):
                ui.label(f"Daily notes go {note}, named {fmt}.").classes("pp-muted")
                link = ui.label("Change").classes("pp-cal-link")
                link.on("click", lambda _e: self._open_settings())

    def _day(self, d: date, in_month: bool, is_today: bool, marks, active, folder, fmt) -> None:  # type: ignore[no-untyped-def]
        cell = ui.element("div").classes("pp-cal-day")
        if not in_month:
            cell.classes("pp-cal-out")
        if is_today:
            cell.classes("pp-cal-today")
        if active is not None and active == daily_relpath(d, folder, fmt):
            cell.classes("pp-cal-sel")
        cell.on("click", lambda _e, day=d: self._open_day(day))
        mark = marks.get(d)
        with cell:
            ui.label(str(d.day)).classes("pp-cal-num")
            with ui.row().classes("pp-cal-dots no-wrap"):
                if mark is not None:
                    ui.element("span").classes("pp-cal-dot")
                    if mark.open_tasks:
                        ui.element("span").classes("pp-cal-dot pp-cal-dot-open")
