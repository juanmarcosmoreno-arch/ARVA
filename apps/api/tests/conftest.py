import json
import os
import shutil
import subprocess
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
def held_queue(monkeypatch):
    """A task queue whose jobs wait, as when no worker is free: tests run them by calling the worker task."""
    queue = Queue("arva-held", connection=FakeRedis(), is_async=True)
    monkeypatch.setattr(jobs_service, "get_queue", lambda: queue)
    return queue


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def storage_root() -> Path:
    return Path(_STORAGE)


@pytest.fixture
def report_browser_check(tmp_path):
    """Runs scripts/<script> (headless Chromium) on a served tool report; skips visibly without node + playwright."""
    if shutil.which("node") is None or subprocess.run(["node", "-e", "require('playwright')"],
                                                      capture_output=True).returncode:
        pytest.skip("headless Chromium (node with playwright) is not available for the report browser check")

    def check(script: str, response) -> dict:
        (tmp_path / "report.html").write_bytes(response.content)
        keep = ("content-type", "content-security-policy", "x-content-type-options", "referrer-policy")
        (tmp_path / "headers.json").write_text(json.dumps({k: v for k, v in response.headers.items() if k in keep}))
        run = subprocess.run(["node", str(API_ROOT.parents[1] / "scripts" / script), str(tmp_path / "report.html"),
                              str(tmp_path / "headers.json")], capture_output=True, text=True, timeout=300)
        assert run.returncode == 0, run.stdout + run.stderr
        return json.loads(run.stdout)

    return check
