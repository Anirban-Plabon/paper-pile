"""Serving images referenced from notes (``/_pp/asset``).

The editor shows ``![alt](.note.assets/x.png)`` through this route. The path rules live in
``Vault.asset_path`` (images only, ``.<stem>.assets`` as the only hidden folder, no traversal);
in ``--serve`` mode the route sits behind the token gate like everything else.
"""

import mimetypes
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from paper_pile.core import assets, embed
from paper_pile.core.config import Config
from paper_pile.core.profile import avatar_path
from paper_pile.core.settings import sanitized
from paper_pile.core.vault import Vault, VaultError

UPLOAD_HEADER = "x-pp-upload"  # a custom header: a cross-site form post cannot set it
LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}


def _same_site(request: Request) -> bool:
    """Uploads must come from our own page: a custom header is required and an ``Origin``, when the
    browser sends one, must be a loopback address (a web page on the internet cannot post here)."""
    if request.headers.get(UPLOAD_HEADER) != "1":
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True
    host = origin.split("://", 1)[-1].rsplit(":", 1)[0] if not origin.endswith("]") else "[::1]"
    return host in LOOPBACK


# SVG can carry scripts: serve it sandboxed so it can only ever be drawn as an image.
SVG_CSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'"


def make_asset_router(vault: Vault | Callable[[], Vault]) -> APIRouter:
    """``vault`` may be a function giving the open vault (it changes with "Open vault")."""
    current: Callable[[], Vault] = vault if callable(vault) else (lambda: vault)
    router = APIRouter()

    @router.get("/_pp/asset")
    def asset(note: str, path: str) -> FileResponse:
        try:
            target = current().asset_path(note, path)
        except VaultError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc
        return FileResponse(target, media_type=_media_type(target), headers=_headers(target))

    @router.get("/_pp/embed")
    def embedded(note: str, target: str, heading: str = "") -> JSONResponse:
        """The content of ``![[target#heading]]`` written in ``note``, as safe HTML."""
        try:
            current().resolve(note)
        except VaultError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc
        shown = embed.embed(current(), note, target, heading)
        return JSONResponse(
            {
                "path": shown.path,
                "title": shown.title,
                "html": shown.html,
                "message": shown.message,
            },
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/_pp/avatar")
    def avatar(name: str) -> FileResponse:
        """The profile picture (only ``avatar.<ext>`` from the user's config folder)."""
        path = avatar_path(name)
        if path is None:
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(path, media_type=_media_type(path), headers=_headers(path))

    @router.post("/_pp/upload")
    async def upload(request: Request, note: str) -> JSONResponse:
        """Save a pasted / dropped / picked image into the vault's images folder."""
        if not _same_site(request):
            raise HTTPException(status_code=403, detail="forbidden")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > assets.MAX_IMAGE_BYTES:
                return JSONResponse({"error": "image is too large"}, status_code=413)
        try:
            vault = current()
            folder = str(sanitized(Config(vault=vault.root).values)["vault.images_folder"])
            saved = assets.save_image(vault, note, bytes(data), folder)
        except VaultError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"ref": saved.ref, "name": saved.name, "width": saved.width})

    return router


def _media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _headers(path: Path) -> dict[str, str]:
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-cache"}
    if path.suffix.lower() == ".svg":
        headers["Content-Security-Policy"] = SVG_CSP
    return headers
