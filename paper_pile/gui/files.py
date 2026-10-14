"""Serving images referenced from notes (``/_pp/asset``).

The editor shows ``![alt](.note.assets/x.png)`` through this route. The path rules live in
``Vault.asset_path`` (images only, ``.<stem>.assets`` as the only hidden folder, no traversal);
in ``--serve`` mode the route sits behind the token gate like everything else.
"""

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from paper_pile.core.vault import Vault, VaultError

# SVG can carry scripts: serve it sandboxed so it can only ever be drawn as an image.
SVG_CSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'"


def make_asset_router(vault: Vault) -> APIRouter:
    router = APIRouter()

    @router.get("/_pp/asset")
    def asset(note: str, path: str) -> FileResponse:
        try:
            target = vault.asset_path(note, path)
        except VaultError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc
        return FileResponse(target, media_type=_media_type(target), headers=_headers(target))

    return router


def _media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _headers(path: Path) -> dict[str, str]:
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-cache"}
    if path.suffix.lower() == ".svg":
        headers["Content-Security-Policy"] = SVG_CSP
    return headers
