"""A forked process (the RQ worker forks one per job) must not reuse the parent's pooled database connections."""
import os

import pytest
from sqlalchemy import text

from app.db.session import SessionLocal, engine


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs os.fork")
def test_a_forked_child_opens_its_own_connections():
    engine.dispose()  # one pooled connection only, so a child reusing it would report the parent's backend
    with SessionLocal() as db:  # the parent checks a connection out and returns it to the pool
        parent_pid = db.execute(text("select pg_backend_pid()")).scalar_one()
    read, write = os.pipe()
    pid = os.fork()
    if pid == 0:  # child
        os.close(read)
        try:
            with SessionLocal() as db:
                child_pid = db.execute(text("select pg_backend_pid()")).scalar_one()
                db.execute(text("select 1")).scalar_one()
            os.write(write, str(child_pid).encode())
        finally:
            os._exit(0)
    os.close(write)
    os.waitpid(pid, 0)
    child_pid = int(os.read(read, 64).decode() or 0)
    os.close(read)
    assert child_pid and child_pid != parent_pid
    # The parent's pooled connection was left open by the child and still works.
    with SessionLocal() as db:
        assert db.execute(text("select pg_backend_pid()")).scalar_one() == parent_pid
    engine.dispose()
