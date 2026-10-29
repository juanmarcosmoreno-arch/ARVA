"""What ARVA checks when it starts, and the migration step of the API container (docker/api-entrypoint.sh runs
`python -m app.services.startup migrate`, so that a failed migration is in the error log with its traceback)."""
from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.core import errorlog
from app.core.config import get_settings

API_ROOT = Path(__file__).resolve().parents[2]


def alembic_config():
    from alembic.config import Config

    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    return cfg


def migration_state(db) -> dict[str, Any]:
    """The database's revision and the newest this ARVA has ("unknown" when one cannot be read)."""
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    try:
        head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    except Exception:
        head = None
    try:
        current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except SQLAlchemyError:
        db.rollback()
        current = None
    return {"current": current or "unknown", "head": head or "unknown", "up_to_date": bool(current and current == head)}


def summary() -> dict[str, Any]:
    """The configuration summary of the application log: settings that explain behaviour, no paths or secrets."""
    s = get_settings()
    return {**errorlog.build(), "environment": s.environment, "queue_async": s.task_queue_async,
            "import_folders": len(s.import_roots), "external_database_folders": len(s.external_db_roots),
            "tool_threads_cap": s.tool_threads, "tool_memory_gb_cap": s.tool_memory_gb,
            "tool_timeout_seconds": s.tool_timeout_seconds, "min_free_bytes": s.min_free_bytes,
            "backup_interval_hours": s.backup_interval_hours, "backup_keep": s.backup_keep,
            "python": platform.python_version(), "platform": f"{platform.system()} {platform.machine()}"}


def check() -> None:
    """Pending migrations, registered databases whose folder is missing, and tools that are installed but cannot be
    used, each kept in the error log; a summary of the tools in the application log."""
    from arva_tools import ToolStatus
    from arva_tools.registry import detect_all
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import DatabaseStatus, ReferenceDatabase
    from app.services import locations

    try:
        with SessionLocal() as db:
            m = migration_state(db)
            rows = db.execute(select(ReferenceDatabase.kind, ReferenceDatabase.key, ReferenceDatabase.path).where(
                ReferenceDatabase.status.in_((DatabaseStatus.installed, DatabaseStatus.registered)),
                ReferenceDatabase.path.isnot(None))).all()
        if not m["up_to_date"] and "unknown" not in (m["current"], m["head"]):
            errorlog.record("api", "error", "startup_migrations_pending", params=m)
        missing = [f"{kind}:{key}" for kind, key, path in rows if not locations.folder_available(path)]
        if missing:
            errorlog.record("api", "warning", "startup_databases_unavailable", params={"count": len(missing)},
                            details={"databases": missing[:50]})
        tools = detect_all()
        unusable = [t for t in tools if t.status in (ToolStatus.incompatible, ToolStatus.failed)]
        if unusable:
            errorlog.record("api", "warning", "startup_tools_unusable",
                            params={"tools": ", ".join(t.info.id for t in unusable)},
                            details={"tools": [{"id": t.info.id, "status": t.status.value, "version": t.version,
                                                "reason": t.reason} for t in unusable]})
        errorlog.info("startup_checks", "Start-up checks done", migrations=m,
                      tools={t.info.id: t.status.value for t in tools}, databases_unavailable=len(missing))
    except Exception as exc:
        errorlog.record("api", "warning", "startup_checks_failed", exc=exc)


def migrate() -> int:
    from alembic import command

    try:
        command.upgrade(alembic_config(), "head")
    except Exception as exc:
        errorlog.record("api", "error", "startup_migration_failed", exc=exc)
        return 1
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["migrate"]:
        print("usage: python -m app.services.startup migrate", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(migrate())
