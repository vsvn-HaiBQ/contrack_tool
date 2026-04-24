from __future__ import annotations

from celery import Celery

from app.core.config import settings


def _broker_url() -> str:
    # Use a different Redis logical DB than session_store (db 0) to keep queues isolated.
    base = settings.redis_url.rstrip("/")
    if base.endswith("/0"):
        return base[:-2] + "/1"
    return base + "/1"


celery_app = Celery(
    "contrack",
    broker=_broker_url(),
    backend=_broker_url(),
    include=["app.modules.git_eol.tasks"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=60 * 30,
    task_soft_time_limit=60 * 25,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    broker_connection_retry_on_startup=True,
    result_expires=60 * 60,
)
