from pathlib import Path
from typing import Any

import pytest

from paper_pile import cli
from paper_pile.core.vault import META_DIR


class Launched:
    """Captures what the CLI would have started."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Launched:
    from paper_pile.gui import app

    rec = Launched()
    monkeypatch.setattr(app, "run_native", lambda v: rec.calls.append(("native", (v,))))
    monkeypatch.setattr(app, "run_serve", lambda v, p, t: rec.calls.append(("serve", (v, p, t))))
    state = tmp_path / "state"
    monkeypatch.setattr(cli, "load_last_vault", lambda: _load(state))
    monkeypatch.setattr(cli, "save_last_vault", lambda v: _save(state, v))
    return rec


def _load(state: Path) -> Path | None:
    from paper_pile.core.session import load_last_vault

    return load_last_vault(state)


def _save(state: Path, vault: Path) -> None:
    from paper_pile.core.session import save_last_vault

    save_last_vault(vault, state)


def test_path_form_opens_native_and_creates_meta(launched: Launched, tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    assert cli.main([str(vault)]) == 0
    assert launched.calls == [("native", (vault.resolve(),))]
    assert (vault / META_DIR).is_dir()


def test_dot_form(launched: Launched, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    cli.main(["."])
    assert launched.calls == [("native", (tmp_path.resolve(),))]


def test_no_arg_reopens_last_vault(launched: Launched, tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    cli.main([str(vault)])
    launched.calls.clear()
    cli.main([])
    assert launched.calls == [("native", (vault.resolve(),))]


def test_no_arg_no_last_non_interactive_errors(
    launched: Launched, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
    assert "none remembered" in capsys.readouterr().err
    assert launched.calls == []


def test_no_arg_prompts_on_tty(
    launched: Launched, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: str(tmp_path))
    cli.main([])
    assert launched.calls == [("native", (tmp_path.resolve(),))]


def test_missing_vault_errors_and_creates_nothing(launched: Launched, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([str(tmp_path / "typo")])
    assert exc.value.code == 2
    assert not (tmp_path / "typo").exists()


def test_serve_default_port_and_random_token(
    launched: Launched, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["--serve", str(tmp_path)])
    cli.main(["--serve", str(tmp_path)])
    (kind1, (v1, port1, tok1)), (_, (_, _, tok2)) = launched.calls
    assert kind1 == "serve" and v1 == tmp_path.resolve() and port1 == 8080
    assert len(tok1) >= 16 and tok1 != tok2
    out = capsys.readouterr().out
    assert f"http://127.0.0.1:8080/?token={tok1}" in out


def test_serve_custom_port(launched: Launched, tmp_path: Path) -> None:
    cli.main(["--serve", str(tmp_path), "--port", "9001"])
    assert launched.calls[0][1][1] == 9001


def test_serve_without_path_uses_last(launched: Launched, tmp_path: Path) -> None:
    cli.main([str(tmp_path)])
    cli.main(["--serve"])
    assert launched.calls[1][0] == "serve" and launched.calls[1][1][0] == tmp_path.resolve()


@pytest.mark.parametrize(
    "argv", [["--port", "9000"], ["--serve", "--port", "0"], ["--serve", "--port", "70000"]]
)
def test_bad_port_usage(launched: Launched, tmp_path: Path, argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([str(tmp_path), *argv])
    assert exc.value.code == 2
    assert launched.calls == []
