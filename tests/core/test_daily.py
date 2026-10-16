from datetime import date, datetime

import pytest

from paper_pile.core.daily import (
    daily_relpath,
    day_marks,
    format_date,
    format_problem,
    month_grid,
    new_daily_text,
    shift_month,
)
from paper_pile.core.templates import render_template
from paper_pile.core.vault import Vault

D = date(2026, 10, 1)  # a Thursday, ISO week 40


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        ("YYYY-MM-DD", "2026-10-01"),
        ("YY/M/D", "26/10/1"),
        ("dddd, D MMMM YYYY", "Thursday, 1 October 2026"),
        ("ddd MMM DD", "Thu Oct 01"),
        ("YYYY-[W]WW", "2026-W40"),
        ("[Day] DD", "Day 01"),
    ],
)
def test_format_date(fmt: str, expected: str) -> None:
    assert format_date(D, fmt) == expected


def test_format_time_tokens() -> None:
    assert format_date(datetime(2026, 10, 1, 9, 5), "HH:mm") == "09:05"


@pytest.mark.parametrize("fmt", ["", "YYYY-MM", "../DD", "YYYY/./DD", "DD:MM", "/DD", "YYYY//DD"])
def test_bad_formats_are_refused(fmt: str) -> None:
    assert format_problem(fmt)


@pytest.mark.parametrize("fmt", ["YYYY-MM-DD", "YYYY/MM/YYYY-MM-DD", "dddd D MMMM"])
def test_good_formats(fmt: str) -> None:
    assert format_problem(fmt) == ""


def test_daily_relpath() -> None:
    assert daily_relpath(D, "", "YYYY-MM-DD") == "2026-10-01.md"
    assert daily_relpath(D, "Daily/", "YYYY/MM/DD") == "Daily/2026/10/01.md"
    assert daily_relpath(D, "Daily", "") == "Daily/2026-10-01.md"


def test_month_grid_is_six_monday_first_weeks() -> None:
    weeks = month_grid(2026, 10, today=date(2026, 10, 16))
    assert len(weeks) == 6 and all(len(w.days) == 7 for w in weeks)
    assert weeks[0].days[0].date == date(2026, 9, 28) and not weeks[0].days[0].in_month
    assert weeks[0].number == 40 and weeks[1].number == 41
    thursday = weeks[0].days[3]
    assert thursday.date == D and thursday.in_month
    assert [d.date for w in weeks for d in w.days if d.is_today] == [date(2026, 10, 16)]
    assert weeks[-1].days[-1].date == date(2026, 11, 8)


def test_month_grid_february_and_year_edges() -> None:
    feb = month_grid(2027, 2, today=date(2027, 2, 1))
    assert feb[0].days[0].date == date(2027, 2, 1) and feb[0].days[0].in_month
    jan = month_grid(2026, 1, today=date(2026, 1, 1))
    assert jan[0].days[0].date == date(2025, 12, 29) and jan[0].number == 1


def test_shift_month_wraps_years() -> None:
    assert shift_month(2026, 12, 1) == (2027, 1)
    assert shift_month(2026, 1, -1) == (2025, 12)
    assert shift_month(2026, 10, 0) == (2026, 10)
    assert shift_month(2026, 3, -15) == (2024, 12)


def test_day_marks_and_open_tasks(tmp_path) -> None:
    vault = Vault(tmp_path)
    vault.create_note("Daily/2026-10-01.md", "# one\n- [x] done\n")
    vault.create_note("Daily/2026-10-02.md", "- [ ] still open\n")
    vault.create_note("Daily/2026-10-03.md", "> - [ ] quoted task\n")
    marks = day_marks(vault, "Daily", "YYYY-MM-DD", [date(2026, 10, i) for i in range(1, 6)])
    assert set(marks) == {date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)}
    assert not marks[date(2026, 10, 1)].open_tasks
    assert marks[date(2026, 10, 2)].open_tasks and marks[date(2026, 10, 3)].open_tasks


def test_new_daily_text_uses_the_template_for_that_day(tmp_path) -> None:
    vault = Vault(tmp_path)
    vault.create_note("Templates/Daily.md", "# {{title}}\n{{date:dddd}} {{date}} {{date:D MMM}}\n")
    now = datetime(2026, 10, 16, 8, 30)
    text = new_daily_text(vault, "Templates/Daily.md", D, now, "YYYY-MM-DD")
    assert text == "# 2026-10-01\nThursday 2026-10-01 1 Oct\n"


def test_new_daily_text_falls_back_without_a_template(tmp_path) -> None:
    vault = Vault(tmp_path)
    now = datetime(2026, 10, 16, 8, 30)
    assert new_daily_text(vault, "", D, now, "YYYY-MM-DD") == "# 2026-10-01\n\n"
    assert new_daily_text(vault, "gone.md", D, now, "YYYY/MM/DD") == "# 01\n\n"


def test_render_template_plain_placeholders_still_work() -> None:
    out = render_template("{{title}} {{date}} {{time}}", title="T", now=datetime(2026, 1, 2, 3, 4))
    assert out == "T 2026-01-02 03:04"
