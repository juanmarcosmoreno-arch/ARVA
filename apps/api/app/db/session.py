"""Database engine and session management."""
import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def forget_inherited_connections() -> None:
    """In a forked process, drop the pooled connections inherited from the parent without closing them.

    The RQ worker forks one process per job after it has used the database itself (worker events, reconciliation);
    a child that reused one of those pooled connections would share its socket with the parent, which corrupts the
    session (psycopg: DuplicatePreparedStatement "prepared statement \"_pg3_0\" already exists"). This is
    SQLAlchemy's documented recipe for os.fork(): Engine.dispose(close=False) in the child."""
    engine.dispose(close=False)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=forget_inherited_connections)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
