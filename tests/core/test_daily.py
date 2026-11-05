import time
from datetime import date, datetime
from pathlib import Path

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


def test_day_marks_cache_rereads_only_changed_notes(tmp_path, monkeypatch) -> None:
    vault = Vault(tmp_path)
    vault.create_note("Daily/2026-10-01.md", "- [ ] open\n")
    days = [date(2026, 10, i) for i in range(1, 4)]
    cache: dict[str, tuple[float, bool]] = {}
    assert day_marks(vault, "Daily", "YYYY-MM-DD", days, cache)[days[0]].open_tasks
    reads: list[str] = []
    read = vault.read_text
    monkeypatch.setattr(vault, "read_text", lambda rel: reads.append(str(rel)) or read(rel))
    assert day_marks(vault, "Daily", "YYYY-MM-DD", days, cache)[days[0]].open_tasks
    assert reads == []  # unchanged: answered from the cache
    time.sleep(0.02)
    vault.write_text("Daily/2026-10-01.md", "- [x] done\n")
    assert not day_marks(vault, "Daily", "YYYY-MM-DD", days, cache)[days[0]].open_tasks
    assert reads == ["Daily/2026-10-01.md"]


def test_day_marks_nested_format_missing_folder_and_escaping_link(tmp_path) -> None:
    vault = Vault(tmp_path / "v")
    vault.create_note("J/2026/10-02.md", "x")
    outside = tmp_path / "secret.md"
    outside.write_text("- [ ] s")
    (vault.root / "J" / "2026" / "10-03.md").symlink_to(outside)
    days = [date(2026, 10, i) for i in range(1, 4)] + [date(2025, 1, 1)]
    assert set(day_marks(vault, "J", "YYYY/MM-DD", days)) == {date(2026, 10, 2)}
    assert day_marks(vault, "Nope", "YYYY-MM-DD", days) == {}


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


def test_untouched_daily_notes_can_take_the_template(tmp_path: Path) -> None:
    from paper_pile.core.daily import untouched_daily

    (tmp_path / "tpl.md").write_text("## Plan {{date}}\n\n- \n")
    vault = Vault(tmp_path)
    day, now = date(2026, 10, 22), datetime(2026, 10, 22, 9, 30)
    fmt = "YYYY-MM-DD"
    plain = "# 2026-10-22\n\n"
    titled = "---\ntitle: 2026-10-22\n---\n# 2026-10-22\n\n"
    templated_titled = "---\ntitle: 2026-10-22\n---\n## Plan 2026-10-22\n\n- \n"
    for text in (plain, titled, titled.replace("\n", "\r\n"), templated_titled):
        assert untouched_daily(text, vault, "tpl.md", day, now, fmt), text
    assert not untouched_daily(plain + "wrote something\n", vault, "tpl.md", day, now, fmt)
    own_title = "---\ntitle: Mine\n---\n# 2026-10-22\n"
    assert not untouched_daily(own_title, vault, "tpl.md", day, now, fmt)
    assert not untouched_daily(templated_titled, vault, "", day, now, fmt)  # template not set


# ---- the tree's date order (user, 2026-11-04) ----------------------------------------------


def test_daily_date_reads_names_back() -> None:
    from paper_pile.core.daily import daily_date

    assert daily_date("d/2026-11-04.md", "d") == date(2026, 11, 4)
    assert daily_date("d/2026/November/04 Wed.md", "d", "YYYY/MMMM/DD ddd") == date(2026, 11, 4)
    assert daily_date("d/4.11.26.md", "d", "D.M.YY") == date(2026, 11, 4)
    assert daily_date("other/2026-11-04.md", "d") is None  # outside the folder
    assert daily_date("d/2026-13-01.md", "d") is None  # no such day
    assert daily_date("d/plan.md", "d") is None
    assert daily_date("d/2026-11-04 copy.md", "d") is None


def test_daily_order_newest_first_and_today_shown_first() -> None:
    from paper_pile.core.daily import daily_order
    from paper_pile.core.vault import TreeEntry

    names = ["2026-11-01.md", "2026-11-06.md", "2026-11-04.md", "plan.md", "2026-10-30.md"]
    entries = [TreeEntry("sub", "d/sub", True)] + [TreeEntry(n, f"d/{n}", False) for n in names]
    ordered, first = daily_order(entries, "d", "YYYY-MM-DD", date(2026, 11, 4))
    assert [e.name for e in ordered] == [
        "sub",
        "2026-11-06.md",
        "2026-11-04.md",
        "2026-11-01.md",
        "2026-10-30.md",
        "plan.md",
    ]
    assert first == "d/2026-11-04.md"
    # no note for today: the latest day before it comes first
    _, first = daily_order(entries[:2] + entries[4:], "d", "YYYY-MM-DD", date(2026, 11, 5))
    assert first == "d/2026-11-01.md"


# ---- names follow the format setting (user, 2026-11-04) ------------------------------------


def test_daily_renames_only_notes_named_by_the_old_format(tmp_path: Path) -> None:
    from paper_pile.core.daily import daily_renames

    vault = Vault(tmp_path)
    vault.create_folder("d")
    for name in ("2026-11-04", "2026-11-05", "plan", "04-11-2026x"):
        vault.create_note(f"d/{name}.md", "x\n")
    plan = daily_renames(vault, "d", ["YYYY-MM-DD"], "DD-MM-YYYY")
    assert [(r.old, r.new) for r in plan] == [
        ("d/2026-11-04.md", "d/04-11-2026.md"),
        ("d/2026-11-05.md", "d/05-11-2026.md"),
    ]
    nested = daily_renames(vault, "d", ["YYYY-MM-DD"], "YYYY/MM/DD")
    assert nested[0].new == "d/2026/11/04.md"
    assert daily_renames(vault, "d", ["YYYY-MM-DD"], "YYYY-MM-DD") == []
    assert daily_renames(vault, "d", ["YYYY-MM-DD"], "YYYY-MM") == []  # no day: refused


def test_retitle_daily_changes_only_the_apps_title() -> None:
    from paper_pile.core.daily import apply_edits, retitle_daily

    text = "---\ntitle: 2026-11-04\n---\n# 2026-11-04\n\nMet on 2026-11-04.\n"
    edits = retitle_daily(text, "2026-11-04", "04.11.2026")
    assert (
        apply_edits(text, edits)
        == '---\ntitle: "04.11.2026"\n---\n# 04.11.2026\n\nMet on 2026-11-04.\n'
    )
    own = '---\ntitle: "Launch day"\n---\n# Launch\n'
    assert retitle_daily(own, "2026-11-04", "04.11.2026") == []
    later = "Notes first\n\n# Something\n\n# 2026-11-04\n"  # only the FIRST heading is the title
    assert retitle_daily(later, "2026-11-04", "x") == []


def test_daily_renames_without_a_record_reads_the_names_the_folder_has(tmp_path: Path) -> None:
    """The bug the user hit: no record yet, notes named DD-MM-YYYY (not the default)."""
    from paper_pile.core.daily import daily_renames

    vault = Vault(tmp_path)
    vault.create_folder("d")
    for name in ("05-11-2026", "13-10-2026", "31-10-2026", "12-Oct-2026", "plan"):
        vault.create_note(f"d/{name}.md", "x\n")
    plan = {r.old: (r.new, r.old_fmt) for r in daily_renames(vault, "d", [], "DD-MMM-YYYY")}
    assert plan == {  # 05-11 is read as day-month: that format names all three
        "d/05-11-2026.md": ("d/05-Nov-2026.md", "DD-MM-YYYY"),
        "d/13-10-2026.md": ("d/13-Oct-2026.md", "DD-MM-YYYY"),
        "d/31-10-2026.md": ("d/31-Oct-2026.md", "DD-MM-YYYY"),
    }
    # the notes already named by the current format stay; only the odd one out moves
    back = daily_renames(vault, "d", [], "DD-MM-YYYY")
    assert [(r.old, r.new) for r in back] == [("d/12-Oct-2026.md", "d/12-10-2026.md")]
    # a recorded format is trusted before a guess: 05-11 named as month-day
    known = daily_renames(vault, "d", ["MM-DD-YYYY"], "YYYY-MM-DD")
    assert ("d/05-11-2026.md", "d/2026-05-11.md") in [(r.old, r.new) for r in known]


def test_synced_formats_history_round_trips(tmp_path: Path) -> None:
    from paper_pile.core.daily import set_synced_format, synced_formats

    (tmp_path / ".paper-pile").mkdir()
    assert synced_formats(tmp_path) == []  # never recorded
    set_synced_format(tmp_path, "DD-MM-YYYY")
    set_synced_format(tmp_path, "DD-MMM-YYYY")
    assert synced_formats(tmp_path) == ["DD-MMM-YYYY", "DD-MM-YYYY"]
    set_synced_format(tmp_path, "DD-MM-YYYY")
    assert synced_formats(tmp_path) == ["DD-MM-YYYY", "DD-MMM-YYYY"]
    (tmp_path / ".paper-pile" / "daily.json").write_text('{"format": "YYYY.MM.DD"}')  # old record
    assert synced_formats(tmp_path) == ["YYYY.MM.DD"]
    (tmp_path / ".paper-pile" / "daily.json").write_text("not json")
    assert synced_formats(tmp_path) == []
