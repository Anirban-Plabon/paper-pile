import json
from pathlib import Path

from paper_pile.core.session import load_last_vault, save_last_vault


def test_round_trip(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    state = tmp_path / "state"
    assert load_last_vault(state) is None
    save_last_vault(vault, state)
    assert load_last_vault(state) == vault


def test_missing_vault_is_ignored(tmp_path: Path) -> None:
    vault = tmp_path / "gone"
    vault.mkdir()
    save_last_vault(vault, tmp_path / "state")
    vault.rmdir()
    assert load_last_vault(tmp_path / "state") is None


def test_corrupt_state_is_ignored(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "last_vault.json").write_text("{not json")
    assert load_last_vault(state) is None
    (state / "last_vault.json").write_text(json.dumps({"other": 1}))
    assert load_last_vault(state) is None
