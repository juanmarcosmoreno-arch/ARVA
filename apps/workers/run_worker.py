"""ARVA analysis worker.

Consumes jobs from the Redis queue and executes them outside the HTTP process.
Run from the repository root:

    apps/api/.venv/bin/python apps/workers/run_worker.py
"""
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from redis import Redis
from rq import Queue, SimpleWorker, Worker

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(settings.task_queue_name, connection=connection)
    # Forking after Objective-C runtime initialisation is unsafe on macOS, so
    # jobs run in the worker process itself there; Linux forks one process per job.
    worker_cls = SimpleWorker if platform.system() == "Darwin" else Worker
    worker_cls([queue], connection=connection).work(with_scheduler=False)


if __name__ == "__main__":
    main()
