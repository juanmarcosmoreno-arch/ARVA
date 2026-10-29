"""Settings → Diagnostics: the recent error log entries, the diagnostic report, and the errors the web interface
reports (app.core.errorlog, app.services.diagnostics). Nothing is sent anywhere; the report is for the user to copy
or download."""
from __future__ import annotations

import re
import time
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core import errorlog
from app.core.redaction import clip
from app.db.session import get_db
from app.schemas.schemas import ClientErrorLogged, ClientErrorReport, ErrorEntryRead
from app.services import diagnostics

router = APIRouter(tags=["system"])

MAX_CLIENT_BODY = 16 * 1024
CLIENT_DUPLICATE_SECONDS = 600.0
_client_limit = errorlog.RateLimit(20, 60.0)
_client_seen: dict[str, tuple[float, str]] = {}
_ORIGIN = re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s)]+")
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

# The English texts of the refusals below; the interface has them as api.error.<code>.
MESSAGES = {
    "diagnostics_not_found": "No {what} {value} is known to ARVA: it may be older than the error log keeps.",
    "client_error_too_large": "An error report from the interface may hold at most {limit} bytes.",
    "client_error_rate_limited": "Too many error reports from the interface in a minute; this one was not kept.",
    "client_error_invalid": "The error report from the interface was not in the expected form.",
}


def _refusal(status_code: int, code: str, headers: dict | None = None, **params) -> JSONResponse:
    return JSONResponse(status_code=status_code, headers=headers,
                        content={"detail": MESSAGES[code].format(**params), "code": code, "params": params})


def _summary(e: dict) -> dict:
    job, request = e.get("job") or {}, e.get("request") or {}
    return {"id": e.get("id", "?"), "time": e["time"], "component": e.get("component", "?"),
            "severity": e.get("severity", "?"), "code": e.get("code", "?"), "message": e.get("message") or "",
            "params": e.get("params") if isinstance(e.get("params"), dict) else {}, "route": request.get("route"),
            "job_id": job.get("id"), "job_type": job.get("type"), "correlation_id": e.get("correlation_id")}


@router.get("/system/errors", response_model=list[ErrorEntryRead])
def recent_errors(limit: int = Query(20, ge=1, le=diagnostics.MAX_ERRORS),
                  since_hours: int = Query(168, ge=1, le=diagnostics.MAX_SINCE_HOURS)):
    """The newest error log entries first: id (shown to the user), time, component, severity, code and English
    message. Read from <data folder>/logs/errors.jsonl and this process's entries that could not be written there."""
    return [_summary(e) for e in errorlog.read(limit=limit, since=diagnostics.since_time(since_hours))]


@router.get("/system/diagnostics", responses={200: {"content": {"text/markdown": {}, "application/zip": {}}}})
def diagnostic_report(
    fmt: Literal["markdown", "json", "zip"] = Query("markdown", alias="format"),
    anonymise: bool = Query(False, description="Replace project, sample and file names by project-1, sample-3, …"),
    include_logs: bool = Query(True, description="Tracebacks, the tools' last output lines and job logs"),
    errors: int = Query(20, ge=0, le=diagnostics.MAX_ERRORS, description="How many recent errors"),
    since_hours: int = Query(168, ge=1, le=diagnostics.MAX_SINCE_HOURS, description="Errors of the last N hours"),
    job_id: str | None = Query(None, pattern=UUID, description="Add this job's details"),
    error_id: str | None = Query(None, pattern=f"^{errorlog.ID_PATTERN}$", description="Add this error in full"),
    db: Session = Depends(get_db),
):
    """The diagnostic report, built now and redacted (app.services.diagnostics says what it holds and never holds):
    Markdown ready to paste into a chat, the same as JSON, or both in a zip."""
    opts = diagnostics.Options(anonymise=anonymise, include_logs=include_logs, errors=errors, since_hours=since_hours,
                               job_id=job_id, error_id=error_id)
    try:
        report = diagnostics.build(db, opts)
    except diagnostics.NotFound as exc:
        return _refusal(status.HTTP_404_NOT_FOUND, "diagnostics_not_found", what=exc.what, value=exc.value)
    headers = {"Cache-Control": "no-store"}
    if fmt == "json":
        return JSONResponse(report, headers=headers)
    md = diagnostics.markdown(report)
    if fmt == "markdown":
        return Response(md, media_type="text/markdown; charset=utf-8", headers=headers)
    stamp = report["generated_at"].replace(":", "").replace("-", "")
    return Response(diagnostics.archive(report, md), media_type="application/zip",
                    headers={**headers, "Content-Disposition": f'attachment; filename="arva-diagnostics-{stamp}.zip"'})


def _stack(text: str | None, lines: int = 25) -> list[str] | None:
    """A browser stack without the page's origin, bounded."""
    if not text:
        return None
    return [clip(_ORIGIN.sub("", line.strip()), 300) or "" for line in text.splitlines()[:lines] if line.strip()]


@router.post("/system/client-errors", response_model=ClientErrorLogged, status_code=status.HTTP_201_CREATED)
async def client_error(request: Request):
    """An error of the web interface (error boundary, window.onerror, unhandled rejection, a failed API call), kept
    in the error log with its id returned. At most 16 KB, 20 a minute; the same error again within ten minutes is
    not kept twice (its first id is returned)."""
    length = request.headers.get("content-length")
    if length is not None and (not length.isdigit() or int(length) > MAX_CLIENT_BODY):
        return _refusal(status.HTTP_413_CONTENT_TOO_LARGE, "client_error_too_large", limit=MAX_CLIENT_BODY)
    if not _client_limit.allow():
        return _refusal(status.HTTP_429_TOO_MANY_REQUESTS, "client_error_rate_limited", headers={"Retry-After": "60"})
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_CLIENT_BODY:
            return _refusal(status.HTTP_413_CONTENT_TOO_LARGE, "client_error_too_large", limit=MAX_CLIENT_BODY)
    try:
        report = ClientErrorReport.model_validate_json(bytes(body))
    except ValidationError:
        return _refusal(status.HTTP_422_UNPROCESSABLE_CONTENT, "client_error_invalid")
    key = f"{report.kind}:{report.message[:200]}:{report.api.path if report.api else ''}"
    now = time.monotonic()
    if (seen := _client_seen.get(key)) and now - seen[0] < CLIENT_DUPLICATE_SECONDS:
        return {"id": seen[1], "duplicate": True}
    api = report.api
    route = errorlog.route_template(api.path) if api else None
    params = {"method": api.method, "route": route, "status": api.status} if api else {"message": clip(report.message, 200)}
    details = {"kind": report.kind, "name": report.name, "page": errorlog.route_template(report.page or ""),
               "stack": _stack(report.stack), "component_stack": _stack(report.component_stack, 15),
               "client_commit": report.client_commit, "user_agent": report.user_agent,
               "api": api and {"code": api.code, "error_id": api.error_id}}
    entry_id = await run_in_threadpool(
        errorlog.record, "web", "error", "web_api_failed" if api else "web_error",
        f"{errorlog.MESSAGES['web_api_failed'].format(**params)}: {clip(report.message, 500)}" if api else None,
        params=params, request={"method": api.method, "route": route, "status": api.status} if api else None,
        correlation_id=api.correlation_id if api else None, details={k: v for k, v in details.items() if v})
    if len(_client_seen) > 500:
        _client_seen.clear()
    _client_seen[key] = (now, entry_id)
    return {"id": entry_id, "duplicate": False}
