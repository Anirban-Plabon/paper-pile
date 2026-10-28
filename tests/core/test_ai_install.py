"""The AI part is the optional ``ai`` extra (PLAN §4.26): the app imports and runs without
``ollama``, with AI off and the install hint shown."""

import os
import subprocess
import sys
import textwrap

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


def test_app_modules_do_not_import_ollama_at_start() -> None:
    result = _run("""
        import sys
        import paper_pile.cli, paper_pile.gui.layout
        from paper_pile.core.ai.factory import make_provider
        assert "ollama" not in sys.modules, "ollama imported at start"
    """)
    assert result.returncode == 0, result.stderr


def test_without_ollama_ai_is_off_with_the_install_hint() -> None:
    result = _run("""
        import asyncio, sys
        sys.modules["ollama"] = None  # as if the extra were not installed
        import paper_pile.cli, paper_pile.gui.layout
        from paper_pile.core.ai.factory import make_provider
        from paper_pile.core.settings import feature_on, sanitized
        assert not feature_on({"features": {"ai": True}}, "features.ai")
        assert sanitized({"features": {"ai": True}})["features.ai"] is False
        assert feature_on({}, "features.calendar")
        health = asyncio.run(make_provider(None).health())
        assert not health.ok and "uv sync --extra ai" in health.message, health
    """)
    assert result.returncode == 0, result.stderr


def test_env_switches() -> None:
    try:
        for env, expected in (({"PAPER_PILE_NO_AI": "1"}, False), ({}, True)):
            install.ai_installed.cache_clear()
            old = {k: os.environ.pop(k, None) for k in ("PAPER_PILE_NO_AI", "PAPER_PILE_FAKE_AI")}
            os.environ.update(env)
            try:
                assert install.ai_installed() is expected
            finally:
                for k, v in old.items():
                    os.environ.pop(k, None)
                    if v is not None:
                        os.environ[k] = v
    finally:
        install.ai_installed.cache_clear()
