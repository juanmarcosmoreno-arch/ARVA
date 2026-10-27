import os
import tempfile
from pathlib import Path

_STORAGE = tempfile.mkdtemp(prefix="arva-test-storage-")
os.environ["ARVA_DATABASE_URL"] = os.environ.get(
    "ARVA_TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:arva_dev_password@localhost:5432/arva_test",
)
os.environ["ARVA_STORAGE_ROOT"] = _STORAGE
os.environ["ARVA_TASK_QUEUE_ASYNC"] = "false"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fakeredis import FakeRedis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from rq import Queue  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import jobs as jobs_service  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE qc_results, analysis_jobs, raw_files, samples, projects CASCADE")
        )


@pytest.fixture(autouse=True)
def sync_queue(monkeypatch):
    queue = Queue("arva-test", connection=FakeRedis(), is_async=False)
    monkeypatch.setattr(jobs_service, "get_queue", lambda: queue)
    return queue


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def storage_root() -> Path:
    return Path(_STORAGE)
