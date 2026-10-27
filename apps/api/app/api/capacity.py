"""Refuse uploads that cannot fit, before the multipart body is received and spooled."""
from __future__ import annotations

import re

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services.capacity import InsufficientStorageError, ensure_space


def insufficient_storage_response(exc: InsufficientStorageError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
        content={
            "detail": str(exc),
            "needed_bytes": exc.needed_bytes,
            "available_bytes": exc.capacity.available_for_data_bytes,
        },
    )


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


class UploadCapacityGuard:
    """Pure ASGI middleware for POST {prefix}/samples/{id}/files, checked against Content-Length."""

    def __init__(self, app: ASGIApp, api_prefix: str):
        self.app = app
        self.pattern = re.compile(rf"^{re.escape(api_prefix)}/samples/[^/]+/files/?$")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and self.pattern.match(scope["path"]):
            length = _content_length(scope)
            if length is not None:
                try:
                    ensure_space(length)
                except InsufficientStorageError as exc:
                    await insufficient_storage_response(exc)(scope, receive, send)
                    return
        await self.app(scope, receive, send)
