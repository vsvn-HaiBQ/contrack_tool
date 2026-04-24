from __future__ import annotations

import json
import time
from typing import Any, Iterator
from uuid import uuid4

from redis import Redis

from app.core.config import settings

JOB_TTL_SECONDS = 60 * 60
LOG_TAIL_LIMIT = 5000


def _redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _logs_key(job_id: str) -> str:
    return f"git_eol:job:{job_id}:logs"


def _status_key(job_id: str) -> str:
    return f"git_eol:job:{job_id}:status"


def _channel(job_id: str) -> str:
    return f"git_eol:job:{job_id}:events"


def new_job_id() -> str:
    return uuid4().hex


def create_job(job_id: str, *, user_id: int, kind: str, params: dict[str, Any]) -> None:
    client = _redis()
    payload = {
        "job_id": job_id,
        "user_id": user_id,
        "kind": kind,
        "status": "queued",
        "created_at": time.time(),
        "params": params,
    }
    client.setex(_status_key(job_id), JOB_TTL_SECONDS, json.dumps(payload))
    client.expire(_logs_key(job_id), JOB_TTL_SECONDS)


def get_job(job_id: str) -> dict[str, Any] | None:
    client = _redis()
    data = client.get(_status_key(job_id))
    return json.loads(data) if data else None


def update_job(job_id: str, **changes: Any) -> dict[str, Any] | None:
    client = _redis()
    data = client.get(_status_key(job_id))
    if not data:
        return None
    payload = json.loads(data)
    payload.update(changes)
    client.setex(_status_key(job_id), JOB_TTL_SECONDS, json.dumps(payload))
    client.publish(_channel(job_id), json.dumps({"type": "status", "status": payload}))
    return payload


def append_log(job_id: str, *, level: str, message: str, source: str = "system") -> None:
    entry = {
        "ts": time.time(),
        "level": level,
        "source": source,
        "message": message,
    }
    serialized = json.dumps(entry, ensure_ascii=False)
    client = _redis()
    pipe = client.pipeline()
    pipe.rpush(_logs_key(job_id), serialized)
    pipe.ltrim(_logs_key(job_id), -LOG_TAIL_LIMIT, -1)
    pipe.expire(_logs_key(job_id), JOB_TTL_SECONDS)
    pipe.publish(_channel(job_id), json.dumps({"type": "log", "log": entry}))
    pipe.execute()


def get_logs(job_id: str) -> list[dict[str, Any]]:
    client = _redis()
    raw = client.lrange(_logs_key(job_id), 0, -1)
    return [json.loads(item) for item in raw]


def stream_events(job_id: str, *, heartbeat_seconds: float = 15.0) -> Iterator[dict[str, Any]]:
    """Yield events for a job: replay existing logs + status, then live updates until terminal status."""
    client = _redis()
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(_channel(job_id))
    try:
        for entry in get_logs(job_id):
            yield {"type": "log", "log": entry}
        status_payload = get_job(job_id)
        if status_payload:
            yield {"type": "status", "status": status_payload}
            if status_payload.get("status") in {"succeeded", "failed"}:
                return

        last_beat = time.time()
        while True:
            message = pubsub.get_message(timeout=1.0)
            now = time.time()
            if message is None:
                if now - last_beat >= heartbeat_seconds:
                    last_beat = now
                    yield {"type": "ping", "ts": now}
                continue
            data = message.get("data")
            if not isinstance(data, str):
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            yield event
            last_beat = now
            if event.get("type") == "status":
                status_value = (event.get("status") or {}).get("status")
                if status_value in {"succeeded", "failed"}:
                    return
    finally:
        try:
            pubsub.unsubscribe(_channel(job_id))
            pubsub.close()
        except Exception:
            pass


class JobLogger:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id

    def info(self, message: str, *, source: str = "system") -> None:
        append_log(self.job_id, level="info", message=message, source=source)

    def warn(self, message: str, *, source: str = "system") -> None:
        append_log(self.job_id, level="warn", message=message, source=source)

    def error(self, message: str, *, source: str = "system") -> None:
        append_log(self.job_id, level="error", message=message, source=source)
