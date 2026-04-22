"""HTTP middlewares: request id propagation and a simple in-memory rate limiter."""

from __future__ import annotations

import time
import uuid
from collections import deque
from threading import Lock
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

REQUEST_ID_HEADER: Final[str] = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a stable request id to every response (and to the Request state)."""

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming or uuid.uuid4().hex
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter keyed by client ip + path prefix.

    Defaults: ``max_requests`` per ``window_seconds`` per (ip, route-bucket).
    Uses a per-process in-memory store; suitable for a single-instance MVP.
    """

    def __init__(
        self,
        app,
        *,
        max_requests: int = 120,
        window_seconds: int = 60,
        prefix_filter: str | None = "/api",
    ) -> None:
        super().__init__(app)
        self._max = max_requests
        self._window = window_seconds
        self._prefix = prefix_filter
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _bucket_key(self, request: Request) -> str:
        client_ip = request.client.host if request.client else "unknown"
        # Bucket by first path segment after the prefix to avoid one hot endpoint
        # starving the rest.
        path = request.url.path
        bucket = path.split("/", 3)
        bucket_key = "/".join(bucket[:3]) if len(bucket) >= 3 else path
        return f"{client_ip}:{bucket_key}"

    async def dispatch(self, request: Request, call_next):
        if self._prefix and not request.url.path.startswith(self._prefix):
            return await call_next(request)
        now = time.monotonic()
        cutoff = now - self._window
        key = self._bucket_key(request)
        with self._lock:
            queue = self._buckets.setdefault(key, deque())
            while queue and queue[0] < cutoff:
                queue.popleft()
            if len(queue) >= self._max:
                retry_after = max(1, int(self._window - (now - queue[0])))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests, please retry later"},
                    headers={"Retry-After": str(retry_after)},
                )
            queue.append(now)
        return await call_next(request)
