"""Refuse requests that a web page on another site could have made (spec §33/§39), with or without accounts.

- Host must be one of `allowed_hosts` (localhost by default), so a hostile domain that re-resolves to 127.0.0.1
  (DNS rebinding) is not served.
- A change (any method but GET/HEAD/OPTIONS) whose Origin is neither in `cors_origins` nor this server's own
  origin, or that the browser marks Sec-Fetch-Site: cross-site, is refused. A cross-site form or a no-cors fetch
  needs no CORS preflight, so CORS alone does not stop it; clients that are not browsers send neither header.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings

SAFE = {"GET", "HEAD", "OPTIONS"}


def _hostname(netloc: str) -> str:
    try:
        return (urlsplit(f"//{netloc}").hostname or "").lower()
    except ValueError:
        return ""


class LocalOrigin:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        settings = get_settings()
        host = headers.get("host", "")
        code = None
        if _hostname(host) not in {h.lower() for h in settings.allowed_hosts}:
            code = "request_host_refused"
        elif scope["method"] not in SAFE:
            origin = headers.get("origin")
            if origin is not None and origin not in settings.cors_origins and urlsplit(origin).netloc != host:
                code = "request_cross_site_refused"
            elif headers.get("sec-fetch-site") == "cross-site":
                code = "request_cross_site_refused"
        if code is None:
            await self.app(scope, receive, send)
            return
        detail = ("ARVA only answers pages it serves itself on this computer." if code == "request_cross_site_refused"
                  else "ARVA only answers requests addressed to localhost.")
        await JSONResponse(status_code=status.HTTP_403_FORBIDDEN,
                           content={"detail": detail, "code": code, "params": {}})(scope, receive, send)
