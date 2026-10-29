import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from paper_pile.gui.security import COOKIE, TokenGate

TOKEN = "s3cret-token"
LOCAL = {"host": "127.0.0.1:8080"}


async def home(_request: object) -> PlainTextResponse:
    return PlainTextResponse("ok")


async def ws(socket: WebSocket) -> None:
    await socket.accept()
    await socket.send_text("hi")
    await socket.close()


@pytest.fixture
def client() -> TestClient:
    app = Starlette(routes=[Route("/", home), WebSocketRoute("/ws", ws)])
    return TestClient(TokenGate(app, TOKEN), base_url="http://127.0.0.1:8080")


def test_no_token_rejected(client: TestClient) -> None:
    assert client.get("/").status_code == 401


def test_wrong_token_rejected(client: TestClient) -> None:
    assert client.get("/?token=nope").status_code == 401


def test_token_accepted_and_sets_cookie(client: TestClient) -> None:
    r = client.get(f"/?token={TOKEN}")
    assert r.status_code == 200 and r.text == "ok"
    set_cookie = r.headers["set-cookie"]
    assert f"{COOKIE}={TOKEN}" in set_cookie
    assert "HttpOnly" in set_cookie and "SameSite=Strict" in set_cookie


def test_cookie_authorises_later_requests(client: TestClient) -> None:
    client.get(f"/?token={TOKEN}")
    assert client.get("/").status_code == 200


def test_foreign_host_rejected_even_with_token(client: TestClient) -> None:
    r = client.get(f"/?token={TOKEN}", headers={"host": "evil.example.com"})
    assert r.status_code == 403


def test_localhost_name_allowed(client: TestClient) -> None:
    r = client.get(f"/?token={TOKEN}", headers={"host": "localhost:8080"})
    assert r.status_code == 200


def test_websocket_needs_token(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws", headers=LOCAL):
        pass


def test_websocket_with_cookie_ok(client: TestClient) -> None:
    # TestClient neither replays its cookie jar nor uses base_url's host on websocket
    # handshakes (browsers do both), so send them explicitly.
    with client.websocket_connect("/ws", headers={**LOCAL, "cookie": f"{COOKIE}={TOKEN}"}) as sock:
        assert sock.receive_text() == "hi"


def test_websocket_wrong_cookie_rejected(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws", headers={**LOCAL, "cookie": f"{COOKIE}=wrong"}),
    ):
        pass


def _svg(_request: object) -> PlainTextResponse:
    return PlainTextResponse("<svg/>", headers={"Content-Security-Policy": "sandbox"})


def test_image_policy_on_every_response() -> None:
    from paper_pile.gui.security import ImagePolicy

    app = Starlette(routes=[Route("/", home), Route("/a.svg", _svg)])
    client = TestClient(ImagePolicy(app))
    assert client.get("/").headers["content-security-policy"] == "img-src 'self' data: blob:"
    assert client.get("/a.svg").headers["content-security-policy"] == "sandbox"  # its own kept
