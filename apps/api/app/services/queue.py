"""Task queue access. Heavy analyses always run in worker processes."""
from functools import lru_cache

from redis import Redis
from rq import Queue

from app.core.config import get_settings


@lru_cache
def get_queue() -> Queue:
    settings = get_settings()
    return Queue(
        settings.task_queue_name,
        connection=Redis.from_url(settings.redis_url),
        is_async=settings.task_queue_async,
        default_timeout=24 * 3600,
    )
