"""Refuse metadata-table uploads above the size limit before the multipart body is received and spooled."""
from __future__ import annotations

import re

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.capacity import _content_length
from app.core.config import get_settings

# Room for the multipart framing and the small form fields sent next to the file.
FORM_OVERHEAD_BYTES = 1024 * 1024


class MetadataUploadLimit:
    """Pure ASGI middleware for POST {prefix}/projects/{id}/metadata/(preview|apply), checked against Content-Length."""

    def __init__(self, app: ASGIApp, api_prefix: str):
        self.app = app
        self.pattern = re.compile(rf"^{re.escape(api_prefix)}/projects/[^/]+/metadata/(?:preview|apply)/?$")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and self.pattern.match(scope["path"]):
            length = _content_length(scope)
            limit = get_settings().metadata_max_bytes
            if length is None:
                response = JSONResponse(
                    status_code=status.HTTP_411_LENGTH_REQUIRED,
                    content={"detail": "Metadata uploads must send a Content-Length header."},
                )
                await response(scope, receive, send)
                return
            if length > limit + FORM_OVERHEAD_BYTES:
                response = JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": f"The file is larger than {limit:,} bytes, the limit for metadata tables "
                                       "(ARVA_METADATA_MAX_BYTES)."},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
