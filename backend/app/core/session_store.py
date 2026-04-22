from __future__ import annotations

import json
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings


class SessionStore:
    def __init__(self) -> None:
        self._redis = Redis.from_url(settings.redis_url, decode_responses=True)

    def _client(self) -> Redis:
        try:
            self._redis.ping()
        except RedisError as exc:
            raise RuntimeError("Redis session store is unavailable") from exc
        return self._redis

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._client().setex(key, settings.session_ttl_seconds, json.dumps(value))

    def get(self, key: str) -> dict[str, Any] | None:
        data = self._client().get(key)
        return json.loads(data) if data else None

    def delete(self, key: str) -> None:
        self._client().delete(key)


session_store = SessionStore()
