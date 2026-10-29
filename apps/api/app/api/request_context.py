"""Every API request gets a correlation id (the X-ARVA-Correlation-Id response header): the jobs it creates record it
and the worker runs them under it, so that an error log entry of the request, of its jobs and of the web interface
can be linked. Coded refusals (a JSON body with "code", status 4xx or 503) are kept at info level, bounded."""
from __future__ import annotations

import json

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import errorlog

HEADER = "x-arva-correlation-id"
_MAX_BODY = 16 * 1024


def route_of(scope: Scope) -> str:
    """The route template (e.g. /api/v1/jobs/{job_id}), never the values in the path or the query."""
    path = scope.get("path", "")
    template = getattr(scope.get("route"), "path", None)
    if not template:
        return errorlog.route_template(path)
    # The route's own path leaves out the prefix its router was included with.
    parts = path.split("/")
    prefix = "/".join(parts[:max(1, len(parts) - len(template.split("/")) + 1)])
    return errorlog.route_template(prefix) + template


class RequestContext:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cid = errorlog.new_correlation_id()
        scope.setdefault("state", {})["correlation_id"] = cid
        token = errorlog.correlation.set(cid)
        response: dict = {"status": 0, "capture": False, "body": b""}

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[HEADER] = cid
                status = message["status"]
                response["status"] = status
                response["capture"] = (400 <= status < 500 or status in (503, 507)) and \
                    headers.get("content-type", "").startswith("application/json")
            elif message["type"] == "http.response.body" and response["capture"]:
                response["body"] += message.get("body", b"")[:_MAX_BODY - len(response["body"])]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            errorlog.correlation.reset(token)
        if response["capture"]:
            await self._refusal(scope, response["status"], response["body"], cid)

    @staticmethod
    async def _refusal(scope: Scope, status: int, body: bytes, cid: str) -> None:
        try:
            data = json.loads(body)
        except ValueError:
            return
        if not isinstance(data, dict) or not isinstance(data.get("code"), str):
            return
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        detail = data.get("detail") if isinstance(data.get("detail"), str) else data["code"]
        await run_in_threadpool(errorlog.refusal, data["code"], detail, params, scope["method"], route_of(scope),
                                status, cid)
