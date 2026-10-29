"""Access control for ``--serve`` (web) mode.

Requests must carry the per-run token, either as ``?token=`` (first visit) or in the
``pp_token`` cookie that the first valid visit sets. The ``Host`` header must be a loopback
name, which also blocks DNS-rebinding. Pure ASGI, so it covers HTTP and websockets alike.
"""

import hmac
from collections.abc import Awaitable, Callable, MutableMapping
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

COOKIE = "pp_token"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


def _host_name(host_header: str) -> str:
    if host_header.startswith("["):  # [::1]:8080
        return host_header[1:].split("]", 1)[0]
    return host_header.rsplit(":", 1)[0] if ":" in host_header else host_header


class TokenGate:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    def _matches(self, supplied: str | None) -> bool:
        return supplied is not None and hmac.compare_digest(supplied.encode(), self.token.encode())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if _host_name(headers.get("host", "")) not in LOOPBACK_HOSTS:
            await self._reject(scope, send, 403, b"Forbidden host")
            return
        query = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("token", [None])[0]
        cookie = SimpleCookie(headers.get("cookie", ""))
        cookie_token = cookie[COOKIE].value if COOKIE in cookie else None
        if not (self._matches(query) or self._matches(cookie_token)):
            await self._reject(scope, send, 401, b"Missing or invalid token")
            return
        if scope["type"] == "http" and not self._matches(cookie_token):
            await self.app(scope, receive, self._with_cookie(send))
        else:
            await self.app(scope, receive, send)

    def _with_cookie(self, send: Send) -> Send:
        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                value = f"{COOKIE}={self.token}; HttpOnly; SameSite=Strict; Path=/"
                message["headers"] = [*message.get("headers", []), (b"set-cookie", value.encode())]
            await send(message)

        return wrapped

    @staticmethod
    async def _reject(scope: Scope, send: Send, status: int, body: bytes) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/plain"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


IMAGE_CSP = b"img-src 'self' data: blob:"


class ImagePolicy:
    """Every page may load images only from the app itself (or inline data): nothing on a page,
    an AI answer included, can make the window contact another server by drawing an image
    (PLAN §4.26). A response that sets its own policy (SVG files) keeps it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(k.lower() == b"content-security-policy" for k, _ in headers):
                    headers.append((b"content-security-policy", IMAGE_CSP))
                    message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped)
