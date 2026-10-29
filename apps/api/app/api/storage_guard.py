"""Refuse every change while the data folder cannot be used (its disk is not connected, or another disk is in its
place), before anything is received or written."""
from __future__ import annotations

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services import locations

WRITES = {"POST", "PUT", "PATCH", "DELETE"}


def storage_unavailable_response(exc: locations.StorageUnavailable) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        content={"detail": str(exc), "code": exc.code, "params": exc.params})


class StorageGuard:
    """Pure ASGI middleware for the API's write requests. Settings → Storage and Performance (/system/...) stay
    usable, so that a missing disk can be explained and an adoption confirmed."""

    def __init__(self, app: ASGIApp, api_prefix: str):
        self.app = app
        self.prefix = api_prefix
        self.exempt = f"{api_prefix}/system/"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if (scope["type"] == "http" and scope["method"] in WRITES and path.startswith(self.prefix + "/")
                and not path.startswith(self.exempt)):
            try:
                await run_in_threadpool(locations.ensure_data)
            except locations.StorageUnavailable as exc:
                await storage_unavailable_response(exc)(scope, receive, send)
                return
        await self.app(scope, receive, send)
