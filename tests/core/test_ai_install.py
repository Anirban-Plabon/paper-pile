"""AI runs only when started with ``paper-pile --ai`` (PLAN §4.26): otherwise the app imports and
runs without ``ollama``, with AI off and the reason shown."""

import os
import subprocess
import sys
import textwrap

import pytest

from paper_pile.cli import build_parser
from paper_pile.core.ai import install


def _run(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if not k.startswith("PAPER_PILE_")}
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        env={**clean, **env},
        timeout=120,
    )


CHECK = """
    import asyncio, sys
    {hide}
    import paper_pile.cli, paper_pile.gui.layout
    from paper_pile.core.ai.factory import make_provider
    from paper_pile.core.settings import feature_on, sanitized
    on = feature_on({{"features": {{"ai": True}}}}, "features.ai")
    assert on is {on}, on
    assert sanitized({{"features": {{"ai": True}}}})["features.ai"] is {on}
    assert feature_on({{}}, "features.calendar")
    assert sys.modules.get("ollama") is None, "ollama imported at start"
    health = asyncio.run(make_provider(None).health()) if not {on} else None
    assert health is None or (not health.ok and {hint!r} in health.message), health
"""


def test_without_the_flag_ai_is_off_and_ollama_never_imported() -> None:
    result = _run(CHECK.format(hide="", on=False, hint="paper-pile --ai"))
    assert result.returncode == 0, result.stderr


def test_with_the_flag_ai_is_on() -> None:
    result = _run(CHECK.format(hide="", on=True, hint=""), PAPER_PILE_AI="1")
    assert result.returncode == 0, result.stderr


def test_with_the_flag_but_no_ollama_says_how_to_install() -> None:
    hide = 'sys.modules["ollama"] = None  # as if it were not installed'
    result = _run(CHECK.format(hide=hide, on=False, hint="uv sync"), PAPER_PILE_AI="1")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, install.NOT_STARTED),
        ({"PAPER_PILE_AI": "1"}, ""),
        ({"PAPER_PILE_AI": "1", "PAPER_PILE_NO_AI": "1"}, install.NOT_STARTED),
        ({"PAPER_PILE_FAKE_AI": "1"}, ""),
    ],
)
def test_env_switches(monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: str) -> None:
    for name in ("PAPER_PILE_AI", "PAPER_PILE_NO_AI", "PAPER_PILE_FAKE_AI"):
        monkeypatch.delenv(name, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    install.ai_unavailable.cache_clear()
    assert install.ai_unavailable() == expected


def test_cli_flag() -> None:
    assert build_parser().parse_args(["v", "--ai"]).ai is True
    assert build_parser().parse_args(["v"]).ai is False
