"""Access control for every API route, applied as a dependency of each router (app.main).

With authentication off (the default) nothing is checked: one local user with every permission. With it on:

1. A valid session cookie is required, except for the sign-in routes (PUBLIC).
2. Changes (any method but GET/HEAD/OPTIONS) need the session's CSRF token in the X-CSRF-Token header.
3. Roles: viewers change nothing but their own password and session; ADMIN_ONLY routes, and changes under
   ADMIN_CHANGES, are for administrators.
4. Projects: every path parameter, id-like query parameter and id in a JSON body is resolved to the project that holds
   it (RESOLVERS). The route's own project needs write access for a change and read access otherwise; any other
   project a body refers to (a comparison set's assemblies, ...) needs read access. A path parameter that is neither
   resolvable nor listed in GLOBAL_PARAMS is refused for non-administrators, so a new route cannot slip through
   unchecked (a test lists every route's parameters).
5. Routes without a project in their path that list data of every project are refused for non-administrators unless
   they filter by `visible_projects` (FILTERED).

Refusals and every allowed change or report download are written to the audit log, with the route's template only.
"""
from __future__ import annotations

import email.message
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.api.request_context import route_of
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    AnalysisJob,
    Annotation,
    Assembly,
    BatchRun,
    ComparisonResult,
    ComparisonSet,
    MlstResult,
    Project,
    RawFile,
    Sample,
    SangerIdentification,
    SangerRead,
    SpeciesResult,
    VariantCall,
)
from app.services import auth

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC = {"/auth/status", "/auth/login", "/auth/setup", "/auth/logout"}
# Routes every signed-in user may call whatever their role (their own account and error reports).
SELF_SERVICE = {"/auth/me", "/auth/password", "/auth/directory", "/system/client-errors"}
ADMIN_ONLY = ("/users", "/audit", "/system/diagnostics", "/system/errors", "/system/storage/adopt",
              "/system/backups", "/assist/settings", "/assist/audit", "/imports/browse", "/imports/roots")
ADMIN_CHANGES = ("/databases", "/system", "/tools")
# Library resources shared by every account (not project data): readable by all, changed by analysts and admins.
GLOBAL_PARAMS = {"kind", "fmt", "name", "key", "table", "index", "module", "tool_id", "feature_id", "record_id",
                 "database_id", "workflow_id", "query_id", "user_id"}
# Unscoped list routes that filter their rows to the caller's projects themselves.
FILTERED = {"/projects", "/samples", "/dashboard", "/jobs", "/annotations", "/comparisons", "/comparisons/candidates",
            "/batches", "/mlst", "/species"}
# Unscoped GET routes that show no project data.
GLOBAL_READS = {"/tools", "/tools/libraries", "/metadata/template", "/typing/modules", "/workflows/catalogue",
                "/workflows", "/gene-queries", "/system/storage", "/system/performance", "/system/native-executor", "/auth/me",
                "/comparisons/phylogeny/compare", "/batches/compare", "/batches/queue", "/assist/status"}
DOWNLOADS = re.compile(r"(report|export|download|\.csv|\.json|\.nwk|\.fasta|\.Rtab|/files/|/outputs/|/file$)")


@dataclass(frozen=True)
class Principal:
    """The signed-in account, detached from the database session that checked it."""
    id: str
    username: str
    role: str


def _sample_project(db: Session, sample_id: str | None) -> str | None:
    s = db.get(Sample, sample_id) if sample_id else None
    return s.project_id if s else None


def _via_sample(model) -> Callable[[Session, str], str | None]:
    return lambda db, i: _sample_project(db, getattr(db.get(model, i), "sample_id", None))


def _result_project(db: Session, i: str) -> str | None:
    r = db.get(ComparisonResult, i)
    s = db.get(ComparisonSet, r.set_id) if r else None
    return s.project_id if s else None


def _attr(model, name: str) -> Callable[[Session, str], str | None]:
    return lambda db, i: getattr(db.get(model, i), name, None)


# (route prefix or "" for any route, parameter name, resolver). The first match wins.
RESOLVERS: list[tuple[str, str, Callable[[Session, str], str | None]]] = [
    ("/batches", "run_id", _attr(BatchRun, "project_id")),
    ("/batches/compare", "a", _attr(BatchRun, "project_id")),
    ("/batches/compare", "b", _attr(BatchRun, "project_id")),
    ("/variants/runs", "run_id", _via_sample(VariantCall)),
    ("/mlst", "result_id", _via_sample(MlstResult)),
    ("/species", "result_id", _via_sample(SpeciesResult)),
    ("/comparisons/results", "result_id", _result_project),
    ("/comparisons/phylogeny/compare", "a", _result_project),
    ("/comparisons/phylogeny/compare", "b", _result_project),
    ("/sanger", "read_id", _via_sample(SangerRead)),
    ("/sanger", "identification_id", _via_sample(SangerIdentification)),
    ("", "forward_read_id", _via_sample(SangerRead)),
    ("", "reverse_read_id", _via_sample(SangerRead)),
    ("", "project_id", lambda db, i: i if db.get(Project, i) else None),
    ("", "sample_id", _sample_project),
    ("", "sample_ids", _sample_project),
    ("", "assembly_id", _via_sample(Assembly)),
    ("", "assembly_ids", _via_sample(Assembly)),
    ("", "reference_assembly_id", _via_sample(Assembly)),
    ("", "annotation_id", _via_sample(Annotation)),
    ("", "file_id", _via_sample(RawFile)),
    ("", "file_ids", _via_sample(RawFile)),
    ("", "job_id", _attr(AnalysisJob, "project_id")),
    ("", "set_id", _attr(ComparisonSet, "project_id")),
]
BODY_KEYS = {"project_id", "sample_id", "sample_ids", "assembly_id", "assembly_ids", "reference_assembly_id",
             "annotation_id", "file_id", "file_ids", "job_id", "set_id", "forward_read_id", "reverse_read_id"}


def resolver(route: str, param: str) -> Callable[[Session, str], str | None] | None:
    for prefix, name, fn in RESOLVERS:
        if name == param and (not prefix or route == prefix or route.startswith(prefix + "/")):
            return fn
    return None


def _ids(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value[:64]]
    if isinstance(value, list):
        return [v[:64] for v in value if isinstance(v, str)][:500]
    return []


def _json_body(content_type: str | None) -> bool:
    """Whether FastAPI reads this request's body as JSON (fastapi.routing: no Content-Type at all, or any
    application/json or application/*+json type, matched case-insensitively)."""
    if not content_type:
        return True
    message = email.message.Message()
    message["content-type"] = content_type
    subtype = message.get_content_subtype()
    return message.get_content_maintype() == "application" and (subtype == "json" or subtype.endswith("+json"))


def _body_refs(node: Any, out: list[tuple[str, str]], depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if k in BODY_KEYS:
                out.extend((k, i) for i in _ids(v))
            elif isinstance(v, dict | list):
                _body_refs(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node[:2000]:
            _body_refs(v, out, depth + 1)


MESSAGES = {
    "auth_required": "Sign in to use ARVA.",
    "auth_csrf_failed": "The request did not carry this session's CSRF token. Reload the page and try again.",
    "auth_admin_only": "Only an administrator can do this.",
    "auth_read_only": "Your account can view projects but not change them.",
    "auth_forbidden": "Your account has no access to this project, or only read access.",
    "auth_unchecked_route": "This route is not available to your account.",
}


class AccessDenied(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


def _deny(db: Session, user: Principal | None, status: int, code: str, method: str, route: str,
          project_id: str | None = None) -> AccessDenied:
    if user is not None:
        auth.audit(db, "request", "denied", user, method=method, route=route, project_id=project_id, code=code)
        db.commit()
    return AccessDenied(status, code)


def _template(request: Request) -> str:
    route = route_of(request.scope)
    prefix = get_settings().api_v1_prefix
    return route[len(prefix):] if route.startswith(prefix) else route


async def guard(request: Request) -> None:
    if not get_settings().auth_enabled:
        request.state.user = None
        request.state.visible_projects = None
        return
    route, method = _template(request), request.method
    if route in PUBLIC:
        return
    db = SessionLocal()
    try:
        found = auth.session_user(db, request.cookies.get(auth.SESSION_COOKIE))
        if found is None:
            raise _deny(db, None, 401, "auth_required", method, route)
        row, sess = found
        user = Principal(row.id, row.username, row.role)
        request.state.user = user
        changing = method not in SAFE_METHODS
        if changing and not auth.csrf_ok(sess, request.headers.get(auth.CSRF_HEADER)):
            raise _deny(db, user, 403, "auth_csrf_failed", method, route)
        if route in SELF_SERVICE:
            return
        admin = user.role == "admin"
        if not admin and (route.startswith(ADMIN_ONLY) or (changing and route.startswith(ADMIN_CHANGES))):
            raise _deny(db, user, 403, "auth_admin_only", method, route)
        if changing and user.role == "viewer":
            raise _deny(db, user, 403, "auth_read_only", method, route)
        request.state.visible_projects = None if admin else auth.visible_project_ids(db, user)

        main: set[str] = set()
        other: set[str] = set()
        unresolved = []
        for name, value in request.path_params.items():
            fn = resolver(route, name)
            if fn is None:
                if name not in GLOBAL_PARAMS:
                    unresolved.append(name)
                continue
            pid = fn(db, str(value))
            if pid:
                main.add(pid)
        for name, value in request.query_params.multi_items():
            fn = resolver(route, name)
            if fn is not None and (name.endswith("_id") or name in ("a", "b")):
                pid = fn(db, value[:64])
                if pid:
                    main.add(pid)
        if changing and _json_body(request.headers.get("content-type")):
            try:
                body = json.loads(await request.body() or b"null")
            except ValueError:
                body = None
            refs: list[tuple[str, str]] = []
            _body_refs(body, refs)
            for key, value in refs:
                fn = resolver(route, key)
                pid = fn(db, value) if fn else None
                if pid:
                    (main if key == "project_id" else other).add(pid)
        if admin:
            if changing or DOWNLOADS.search(route):
                auth.audit(db, "request", "allowed", user, method=method, route=route,
                           project_id=next(iter(main), None))
                db.commit()
            return
        if unresolved:
            raise _deny(db, user, 403, "auth_unchecked_route", method, route)
        if not request.path_params and not main and not changing:
            if route not in FILTERED and route not in GLOBAL_READS and not route.startswith("/assist"):
                raise _deny(db, user, 403, "auth_admin_only", method, route)
        for pid in main | other:
            project = db.get(Project, pid)
            level = auth.access(db, user, project) if project else None
            need = "write" if changing and pid in main else "read"
            if level is None or (need == "write" and level != "write"):
                raise _deny(db, user, 403, "auth_forbidden", method, route, pid)
        if changing or DOWNLOADS.search(route):
            auth.audit(db, "request", "allowed", user, method=method, route=route, project_id=next(iter(main), None))
            db.commit()
    finally:
        db.close()


def visible_projects(request: Request) -> set[str] | None:
    """The projects the caller may see (None: all of them)."""
    return getattr(request.state, "visible_projects", None)


def current_user(request: Request) -> Principal | None:
    return getattr(request.state, "user", None)


def keep_visible(rows: list[dict[str, Any]], visible: set[str] | None, key: str = "project_id") -> list[dict]:
    return rows if visible is None else [r for r in rows if r.get(key) in visible]
