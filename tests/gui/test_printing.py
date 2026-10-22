from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from paper_pile.core.config import Config
from paper_pile.core.vault import Vault
from paper_pile.gui import printing
from paper_pile.gui.security import TokenGate

HOST = {"host": "127.0.0.1:8080"}


def _client(token: str | None = None) -> TestClient:
    app = FastAPI()
    if token:
        app.add_middleware(TokenGate, token=token)
    app.include_router(printing.make_print_router())
    return TestClient(app)


def test_stored_pages_are_served_and_unknown_keys_are_not() -> None:
    url = printing.store("<p>page</p>")
    client = _client()
    r = client.get(url, headers=HOST)
    assert r.status_code == 200 and r.text == "<p>page</p>"
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/_pp/print/nope", headers=HOST).status_code == 404


def test_only_the_newest_pages_are_kept() -> None:
    first = printing.store("old")
    for _ in range(printing.KEEP):
        printing.store("newer")
    assert _client().get(first, headers=HOST).status_code == 404


def test_web_mode_needs_the_token() -> None:
    url = printing.store("<p>x</p>")
    client = _client("t0ken")
    assert client.get(url, headers=HOST).status_code == 401
    assert client.get(f"{url}?token=t0ken", headers=HOST).status_code == 200


def test_print_page_uses_the_editor_settings(tmp_path: Path) -> None:
    config = Config(global_path=tmp_path / "g.toml", vault=tmp_path)
    config.set("editor.font_size", 18)
    config.set("print.paper", "Letter")
    (tmp_path / "n.md").write_text("x")
    page = printing.build_print_page(Vault(tmp_path), config, "n.md", "# Hi\n", "n")
    assert "--pp-size: 18px;" in page and "size: 215.9mm 279.4mm" in page
    assert 'src="/pp-static/vendor/pp-editor/print.js?v=' in page
    assert '<h1 data-line="1">Hi</h1>' in page
