"""Optional authentication: setup, sessions, CSRF, roles, project sharing, access control on every route, audit."""
import re
import stat

import pytest
from sqlalchemy import select

from app.api import access
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models import AuditEvent, User
from app.services import auth

PASSWORD = "correct horse battery"


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_enabled", True)
    monkeypatch.setattr(get_settings(), "login_lockout_seconds", 60)


def make_user(username: str, role: str) -> str:
    with SessionLocal() as db:
        u = auth.create_user(db, username, PASSWORD, role, None)
        db.commit()
        return u.id


def login(client, username: str) -> dict:
    client.cookies.clear()
    r = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def test_auth_off_by_default_keeps_the_single_local_user(client):
    assert client.get("/api/v1/auth/status").json() == {"enabled": False, "setup_required": False, "user": None}
    assert client.post("/api/v1/projects", json={"name": "P"}).status_code == 201
    assert client.post("/api/v1/auth/login", json={"username": "x", "password": "y"}).json()["code"] == "auth_disabled"


def test_first_administrator_needs_the_setup_token_from_the_secrets_folder(client, auth_on, storage_root):
    st = client.get("/api/v1/auth/status").json()
    assert st["enabled"] and st["setup_required"] and st["user"] is None
    token_file = storage_root / "secrets" / auth.SETUP_TOKEN_FILE
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(token_file.parent.stat().st_mode) == 0o700
    body = {"username": "admin", "password": PASSWORD, "token": "wrong"}
    assert client.post("/api/v1/auth/setup", json=body).json()["code"] == "auth_setup_token_invalid"
    body["token"] = token_file.read_text()
    r = client.post("/api/v1/auth/setup", json=body)
    assert r.status_code == 201 and r.json()["user"]["role"] == "admin"
    assert not token_file.exists()
    assert client.post("/api/v1/auth/setup", json=body).json()["code"] == "auth_setup_done"
    with SessionLocal() as db:
        assert db.scalar(select(User.password_hash)).startswith("$argon2id$")
    assert client.get("/api/v1/auth/status").json()["user"]["username"] == "admin"


def test_sessions_csrf_and_lockout(client, auth_on):
    make_user("ana", "analyst")
    assert client.get("/api/v1/projects").json()["code"] == "auth_required"
    bad = client.post("/api/v1/auth/login", json={"username": "ana", "password": "nope nope nope"})
    assert bad.status_code == 401 and bad.json()["code"] == "auth_invalid_credentials"
    unknown = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "nope nope nope"})
    assert unknown.json()["code"] == "auth_invalid_credentials"
    csrf = login(client, "ana")
    assert "httponly" in client.post("/api/v1/auth/login", json={"username": "ana", "password": PASSWORD}) \
        .headers["set-cookie"].lower()
    csrf = login(client, "ana")
    assert client.get("/api/v1/projects").status_code == 200
    r = client.post("/api/v1/projects", json={"name": "No token"})
    assert r.status_code == 403 and r.json()["code"] == "auth_csrf_failed"
    assert client.post("/api/v1/projects", json={"name": "P"}, headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert client.post("/api/v1/projects", json={"name": "P"}, headers=csrf).status_code == 201
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/projects").status_code == 401
    client.cookies.clear()
    for _ in range(get_settings().login_max_failures):
        client.post("/api/v1/auth/login", json={"username": "ana", "password": "wrong password!"})
    locked = client.post("/api/v1/auth/login", json={"username": "ana", "password": PASSWORD})
    assert locked.status_code == 429 and locked.json()["code"] == "auth_locked"


def test_roles_sharing_and_project_access(client, auth_on):
    make_user("root", "admin")
    ana_id, bob_id, vic_id = make_user("ana", "analyst"), make_user("bob", "analyst"), make_user("vic", "viewer")
    h = login(client, "ana")
    pid = client.post("/api/v1/projects", json={"name": "Ana's"}, headers=h).json()["id"]
    sample = client.post(f"/api/v1/projects/{pid}/samples", json={"sample_code": "S1"}, headers=h).json()

    h = login(client, "bob")
    assert client.get("/api/v1/projects").json() == []
    assert client.get(f"/api/v1/projects/{pid}").json()["code"] == "auth_forbidden"
    assert client.get(f"/api/v1/samples/{sample['id']}").status_code == 403
    assert client.get("/api/v1/samples").json() == []
    own = client.post("/api/v1/projects", json={"name": "Bob's"}, headers=h).json()["id"]
    # A body that names a sample of a project Bob cannot read is refused before the route runs.
    r = client.post("/api/v1/batches/preview", json={"project_id": own, "sample_ids": [sample["id"]],
                                                      "template_key": "x"}, headers=h)
    assert r.status_code == 403 and r.json()["code"] == "auth_forbidden"
    assert client.put(f"/api/v1/projects/{pid}/shares", json={"user_id": bob_id, "access": "read"},
                      headers=h).status_code == 403

    h = login(client, "ana")
    assert client.put(f"/api/v1/projects/{pid}/shares", json={"user_id": bob_id, "access": "read"},
                      headers=h).status_code == 200
    client.put(f"/api/v1/projects/{pid}/shares", json={"user_id": vic_id, "access": "write"}, headers=h)
    assert client.get("/api/v1/users").json()["code"] == "auth_admin_only"
    assert {u["username"] for u in client.get("/api/v1/auth/directory").json()} == {"root", "ana", "bob", "vic"}

    h = login(client, "bob")
    assert {p["id"] for p in client.get("/api/v1/projects").json()} == {pid, own}
    assert client.get(f"/api/v1/samples/{sample['id']}").status_code == 200
    r = client.patch(f"/api/v1/projects/{pid}", json={"name": "renamed"}, headers=h)
    assert r.status_code == 403 and r.json()["code"] == "auth_forbidden"

    h = login(client, "vic")
    assert client.get(f"/api/v1/projects/{pid}").status_code == 200
    r = client.patch(f"/api/v1/projects/{pid}", json={"name": "renamed"}, headers=h)
    assert r.status_code == 403 and r.json()["code"] == "auth_read_only"
    assert client.post("/api/v1/projects", json={"name": "V"}, headers=h).json()["code"] == "auth_read_only"

    h = login(client, "root")
    assert {p["id"] for p in client.get("/api/v1/projects").json()} == {pid, own}
    assert client.patch(f"/api/v1/users/{ana_id}", json={"role": "viewer"}, headers=h).status_code == 200
    root_id = next(u["id"] for u in client.get("/api/v1/users").json() if u["username"] == "root")
    assert client.patch(f"/api/v1/users/{root_id}", json={"role": "analyst"}, headers=h).json()["code"] == \
        "auth_last_admin"
    events = client.get("/api/v1/audit").json()
    assert any(e["action"] == "request" and e["outcome"] == "denied" and e["username"] == "bob" for e in events)
    assert any(e["action"] == "share" for e in events)
    assert any(e["action"] == "login" and e["outcome"] == "allowed" for e in events)
    assert all("password" not in str(e["detail"]).lower() or e["action"] == "user_update" for e in events)


def test_role_change_ends_the_users_sessions(client, auth_on):
    make_user("root", "admin")
    ana = make_user("ana", "analyst")
    login(client, "ana")
    session = dict(client.cookies)
    h = login(client, "root")
    client.patch(f"/api/v1/users/{ana}", json={"role": "viewer"}, headers=h)
    client.cookies.clear()
    client.cookies.update(session)
    assert client.get("/api/v1/projects").status_code == 401


def test_every_route_parameter_is_resolved_or_declared_global():
    spec = app.openapi()
    prefix = get_settings().api_v1_prefix
    for path in spec["paths"]:
        route = path[len(prefix):] if path.startswith(prefix) else path
        for name in re.findall(r"{(\w+)}", route):
            assert access.resolver(route, name) or name in access.GLOBAL_PARAMS, (route, name)


def test_unscoped_reads_are_filtered_global_or_admin_only():
    spec = app.openapi()
    prefix = get_settings().api_v1_prefix
    for path, ops in spec["paths"].items():
        route = path[len(prefix):] if path.startswith(prefix) else path
        if "get" not in ops or "{" in route or not path.startswith(prefix):
            continue
        assert (route in access.FILTERED or route in access.GLOBAL_READS or route.startswith(access.ADMIN_ONLY)
                or route in access.PUBLIC or route in access.SELF_SERVICE or route.startswith("/assist")
                or route in UNSCOPED_ADMIN_READS), route


# Unscoped reads left to administrators when authentication is on (the guard refuses them to other roles).
UNSCOPED_ADMIN_READS = {"/databases", "/databases/kinds", "/databases/catalogue", "/databases/locations",
                        "/databases/browse", "/databases/detect", "/databases/usage", "/databases/extract/plan",
                        "/databases/amrfinderplus/releases", "/system/errors", "/system/diagnostics"}


def test_audit_rows_never_hold_request_values(client, auth_on):
    make_user("ana", "analyst")
    h = login(client, "ana")
    client.post("/api/v1/projects", json={"name": "Secret name 123"}, headers=h)
    with SessionLocal() as db:
        rows = db.scalars(select(AuditEvent)).all()
    assert rows and all("Secret name" not in str((r.route, r.detail)) for r in rows)
