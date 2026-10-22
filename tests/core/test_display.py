from pathlib import Path

from paper_pile.core.display import (
    Monitor,
    Screen,
    load_cached,
    match_scales,
    parse_monitors,
    save_cached,
)

# A laptop at 150 % left of a 100 % monitor that sits 526 px higher (as Windows reports it)
WINDOWS = "#< CLIXML\n<Objs>noise</Objs>PPMON 0 0 1920 1200 144\r\nPPMON 1920 -526 1920 1080 96\r\n"
# ... and as WSLg reports the same layout to Linux (shifted so nothing is negative)
WSLG = [Screen("rdp-0", 0, 526, 1920, 1200), Screen("rdp-3", 1920, 0, 1920, 1080)]


def test_parse_skips_powershell_noise() -> None:
    assert parse_monitors(WINDOWS) == [
        Monitor(0, 0, 1920, 1200, 1.5),
        Monitor(1920, -526, 1920, 1080, 1.0),
    ]


def test_parse_ignores_bad_rows() -> None:
    assert parse_monitors("PPMON 1 2 x 4 96\nPPMON 0 0 0 10 96\nPPMON 0 0 10 10\nPPMONx\n") == []


def test_match_by_position_after_shifting_layouts() -> None:
    assert match_scales(WSLG, parse_monitors(WINDOWS)) == {"rdp-0": 1.5, "rdp-3": 1.0}


def test_match_falls_back_to_unique_size() -> None:
    moved = [Screen("a", 5000, 0, 1920, 1200)]
    assert match_scales(moved, parse_monitors(WINDOWS)) == {"a": 1.5}


def test_unknown_screens_get_no_scale() -> None:
    twins = [Monitor(0, 0, 1920, 1080, 1.0), Monitor(1920, 0, 1920, 1080, 1.25)]
    assert match_scales([Screen("y", 0, 0, 800, 600)], twins) == {}
    assert match_scales(WSLG, []) == {}


def test_cache_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "monitors.json"
    monitors = parse_monitors(WINDOWS)
    save_cached(path, monitors)
    assert load_cached(path) == monitors
    path.write_text("not json", encoding="utf-8")
    assert load_cached(path) == []
    assert load_cached(tmp_path / "missing.json") == []


def test_work_area_is_read_and_defaults_to_the_whole_monitor() -> None:
    from paper_pile.core.display import match_monitors, work_area

    text = "PPMON 0 0 1920 1200 144 WORK 0 0 1920 1128\nPPMON 1920 -526 1920 1080 96\n"
    laptop, monitor = parse_monitors(text)
    assert work_area(laptop) == (1920, 1128)
    assert work_area(monitor) == (1920, 1080)  # no WORK part (older cache): all of it
    assert match_monitors(WSLG, [laptop, monitor])["rdp-0"] is laptop


def test_taskbar_insets_of_a_maximized_window() -> None:
    from paper_pile.core.display import taskbar_insets

    msi = Monitor(1920, -526, 1920, 1080, 1.0, 1920, 1032, 1920, -526)  # taskbar at the bottom
    assert taskbar_insets(msi, 1080) == (0, 48)
    assert taskbar_insets(msi, 1032) == (0, 0)  # already fits
    top_bar = Monitor(0, 0, 1920, 1080, 1.0, 1920, 1032, 0, 48)  # taskbar at the top
    assert taskbar_insets(top_bar, 1080) == (48, 0)
    assert taskbar_insets(Monitor(0, 0, 1920, 1080, 1.0), 1080) == (0, 0)  # work area unknown
