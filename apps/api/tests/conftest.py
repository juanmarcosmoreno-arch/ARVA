import atexit
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_STORAGE = tempfile.mkdtemp(prefix="arva-test-storage-")
# Every run stores its uploads and tool outputs here (about 20 MB, more with the real annotators).
atexit.register(shutil.rmtree, _STORAGE, ignore_errors=True)
os.environ["ARVA_DATABASE_URL"] = os.environ.get(
    "ARVA_TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:arva_dev_password@localhost:5432/arva_test",
)
os.environ["ARVA_STORAGE_ROOT"] = _STORAGE
os.environ["ARVA_TASK_QUEUE_ASYNC"] = "false"
# An administrator cap, so tool runs get 4 threads whatever the profile (tests of the profiles lift it).
os.environ["ARVA_TOOL_THREADS"] = "4"
# The start-up checks run tool detection in a thread at every TestClient start; tests call them directly.
os.environ["ARVA_STARTUP_CHECKS"] = "false"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fakeredis import FakeRedis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from rq import Queue  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import host, performance  # noqa: E402
from app.services import jobs as jobs_service  # noqa: E402

# A constructed computer, so that resources do not depend on the machine running the tests: no host facts, 8 usable
# CPUs and 64 GB, outside a container.
TEST_DETECTION = host.Detection(host.HostFacts(), host.ContainerFacts(
    usable_cpus=8, cpus_source="affinity", memory_bytes=64 * 1024**3, memory_source="meminfo"))

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
            text("TRUNCATE annotations, qc_results, analysis_jobs, raw_files, samples, projects, reference_databases, "
                 "app_settings CASCADE")
        )


@pytest.fixture(autouse=True)
def detected(monkeypatch):
    """The detection every test sees; a test replaces it with monkeypatch.setattr(performance, "detection", ...)."""
    monkeypatch.setattr(performance, "detection", lambda: TEST_DETECTION)
    return TEST_DETECTION


@pytest.fixture(autouse=True)
def sync_queue(monkeypatch):
    queue = Queue("arva-test", connection=FakeRedis(), is_async=False)
    monkeypatch.setattr(jobs_service, "get_queue", lambda: queue)
    return queue


@pytest.fixture(autouse=True)
def hidden_mlst(monkeypatch, request):
    """mlst is hidden unless a test asks for it (real_mlst, or a stand-in that sets ARVA_TOOL_MLST itself), so that
    its bundled schemes do not appear as a database in the other tests."""
    from arva_tools import registry

    registry._CACHE.pop("mlst", None)
    if "real_mlst" not in request.fixturenames:
        monkeypatch.setenv("ARVA_TOOL_MLST", "/nonexistent/mlst")
    yield
    registry._CACHE.pop("mlst", None)


MOBILE_TOOLS = ("abricate", "mobsuite", "integronfinder", "isescan", "genomad")


@pytest.fixture(autouse=True)
def hidden_mobile_tools(monkeypatch, request):
    """The plasmid, mobile-element and VFDB tools are hidden unless a test asks for them (a fixture named mobile_*),
    so that ABRicate's bundled databases do not appear as databases in the other tests."""
    from arva_tools import registry

    for tool in MOBILE_TOOLS:
        registry._CACHE.pop(tool, None)
    if not any(n.startswith("mobile_") for n in request.fixturenames):
        for tool in MOBILE_TOOLS:
            monkeypatch.setenv(f"ARVA_TOOL_{tool.upper()}", f"/nonexistent/{tool}")
    yield
    for tool in MOBILE_TOOLS:
        registry._CACHE.pop(tool, None)


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
