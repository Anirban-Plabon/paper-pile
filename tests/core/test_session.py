import json
from pathlib import Path

from paper_pile.core.session import (
    SessionState,
    load_last_vault,
    load_session,
    save_last_vault,
    save_session,
)


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


# ---- per-vault session ------------------------------------------------------------------


def test_session_defaults_when_missing(tmp_path: Path) -> None:
    s = load_session(tmp_path)
    assert s == SessionState()
    assert s.pane_widths == {"left": 260, "right": 340}
    assert s.panes_open == {"left": True, "right": True}
    assert s.mode == "live"


def test_session_round_trip(tmp_path: Path) -> None:
    state = SessionState(
        tabs=["a.md", "d/b.md"],
        active="d/b.md",
        pane_widths={"left": 300, "right": 410},
        panes_open={"left": False, "right": True},
        mode="source",
    )
    save_session(tmp_path, state)
    assert (tmp_path / ".paper-pile" / "session.json").is_file()
    assert load_session(tmp_path) == state


def test_session_corrupt_or_wrong_types_fall_back_per_field(tmp_path: Path) -> None:
    meta = tmp_path / ".paper-pile"
    meta.mkdir()
    (meta / "session.json").write_text("{nope")
    assert load_session(tmp_path) == SessionState()
    (meta / "session.json").write_text(
        json.dumps(
            {
                "tabs": ["ok.md", 5],
                "active": 7,
                "pane_widths": {"left": -5, "right": "wide"},
                "panes_open": {"left": "yes", "right": False},
                "mode": "split",
            }
        )
    )
    s = load_session(tmp_path)
    assert s.tabs == [] and s.active is None and s.mode == "live"
    assert s.pane_widths == {"left": 260, "right": 340}
    assert s.panes_open == {"left": True, "right": False}
    (meta / "session.json").write_text("[1, 2]")
    assert load_session(tmp_path) == SessionState()


def test_save_session_failure_is_not_fatal(tmp_path: Path) -> None:
    save_session(tmp_path / "does-not-exist" / "deeper", SessionState())  # no raise
