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


# ---- uploads (paste / drop / picker) ------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x00\x0a\x00\x00\x00\x14" + b"x"
UP = {"host": "127.0.0.1:8080", "x-pp-upload": "1"}


@pytest.fixture
def upload_client(tmp_path: Path) -> tuple[TestClient, Vault]:
    vault = Vault(tmp_path)
    vault.create_note("n.md", "")
    app = FastAPI()
    app.include_router(make_asset_router(vault))
    return TestClient(TokenGate(app, TOKEN), base_url="http://127.0.0.1:8080"), vault


def post(
    c: TestClient, data: bytes, note: str = "n.md", headers: dict[str, str] | None = None
) -> Response:
    return c.post(
        "/_pp/upload", params={"note": note, "token": TOKEN}, content=data, headers=headers or UP
    )


def test_upload_saves_the_image_and_answers_with_its_reference(upload_client) -> None:  # type: ignore[no-untyped-def]
    client, vault = upload_client
    r = post(client, PNG)
    assert r.status_code == 200
    body = r.json()
    assert body["ref"] == f".image/{body['name']}" and body["width"] == 10  # the images folder
    assert vault.asset_path("n.md", body["ref"]).read_bytes() == PNG
    assert post(client, PNG).json() == body  # the same picture again: same file


def test_upload_refuses_non_images(upload_client) -> None:  # type: ignore[no-untyped-def]
    client, vault = upload_client
    r = post(client, b"MZ this is an exe")
    assert r.status_code == 400 and "not a supported image" in r.json()["error"]
    assert not (vault.root / ".n.assets").exists() and not (vault.root / ".image").exists()


def test_upload_needs_the_custom_header_and_a_local_origin(upload_client) -> None:  # type: ignore[no-untyped-def]
    client, vault = upload_client
    assert (
        post(client, PNG, headers={"host": "127.0.0.1:8080"}).status_code == 403
    )  # plain form post
    evil = {**UP, "origin": "https://evil.example"}
    assert post(client, PNG, headers=evil).status_code == 403
    ok = {**UP, "origin": "http://127.0.0.1:8080"}
    assert post(client, PNG, headers=ok).status_code == 200
    assert not list((vault.root).glob(".*.assets/../../evil*"))


def test_upload_needs_the_token(upload_client) -> None:  # type: ignore[no-untyped-def]
    client, _ = upload_client
    r = client.post("/_pp/upload", params={"note": "n.md"}, content=PNG, headers=UP)
    assert r.status_code == 401


def test_upload_rejects_bad_notes_and_huge_bodies(upload_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, vault = upload_client
    for bad in ["../x.md", ".trash/x.md", "n.exe"]:
        assert post(client, PNG, note=bad).status_code == 400
    monkeypatch.setattr("paper_pile.core.assets.MAX_IMAGE_BYTES", 20)
    assert post(client, PNG + b"y" * 50).status_code == 413
    assert not (vault.root / ".n.assets").exists() and not (vault.root / ".image").exists()
