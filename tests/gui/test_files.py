from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import Response
from starlette.testclient import TestClient

from paper_pile.core.vault import Vault
from paper_pile.gui.files import SVG_CSP, make_asset_router
from paper_pile.gui.security import TokenGate

TOKEN = "t0ken"
HOST = {"host": "127.0.0.1:8080"}


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    (root / ".n.assets").mkdir(parents=True)
    (root / ".n.assets" / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / ".n.assets" / "v.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (root / ".n.assets" / "notes.md").write_text("secret note")
    (root / "n.md").write_text("![x](.n.assets/a.png)")
    (root / ".trash").mkdir()
    (root / ".trash" / "old.png").write_bytes(b"png")
    return Vault(root)


@pytest.fixture
def client(vault: Vault) -> TestClient:
    app = FastAPI()
    app.include_router(make_asset_router(vault))
    return TestClient(TokenGate(app, TOKEN), base_url="http://127.0.0.1:8080")


def get(client: TestClient, note: str, path: str, token: bool = True) -> Response:
    qs = {"note": note, "path": path, **({"token": TOKEN} if token else {})}
    return client.get("/_pp/asset", params=qs, headers=HOST)


def test_serves_an_image_with_safe_headers(client: TestClient) -> None:
    r = get(client, "n.md", ".n.assets/a.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in r.headers


def test_svg_is_sandboxed(client: TestClient) -> None:
    r = get(client, "n.md", ".n.assets/v.svg")
    assert r.status_code == 200 and r.headers["content-security-policy"] == SVG_CSP


@pytest.mark.parametrize(
    "path",
    [
        "../../etc/passwd.png",
        "/etc/passwd",
        ".trash/old.png",
        ".n.assets/notes.md",
        ".n.assets/missing.png",
    ],
)
def test_refuses_everything_else_with_404(client: TestClient, path: str) -> None:
    assert get(client, "n.md", path).status_code == 404


def test_unsafe_note_path_is_a_404_not_an_error(client: TestClient) -> None:
    assert get(client, "../n.md", ".n.assets/a.png").status_code == 404


def test_requires_the_token(client: TestClient) -> None:
    assert get(client, "n.md", ".n.assets/a.png", token=False).status_code == 401
