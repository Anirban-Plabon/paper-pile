from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _own_config_dirs(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every test gets empty config / state / cache folders: never the user's own settings."""
    base: Path = tmp_path_factory.mktemp("xdg")
    for name in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(name, str(base / name.lower()))


@pytest.fixture(autouse=True)
def _started_with_ai(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Tests run as ``paper-pile --ai`` (test_ai_install checks the other cases)."""
    from paper_pile.core.ai.install import ai_unavailable

    for name in ("PAPER_PILE_NO_AI", "PAPER_PILE_FAKE_AI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPER_PILE_AI", "1")
    ai_unavailable.cache_clear()
    yield
    ai_unavailable.cache_clear()
