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
