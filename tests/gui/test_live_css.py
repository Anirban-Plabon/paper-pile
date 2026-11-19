"""Live CSS (--live-css): off by default, finds our stylesheets, builds a swap for a changed one."""

from paper_pile.cli import build_parser
from paper_pile.gui import live_css


def test_off_unless_asked(monkeypatch):
    monkeypatch.delenv("PAPER_PILE_LIVE_CSS", raising=False)
    assert not live_css.enabled()
    monkeypatch.setenv("PAPER_PILE_LIVE_CSS", "1")
    assert live_css.enabled()


def test_watches_our_stylesheets():
    assert "app.css" in live_css._mtimes()


def test_cli_flag():
    assert build_parser().parse_args(["--live-css", "."]).live_css
    assert not build_parser().parse_args(["."]).live_css
