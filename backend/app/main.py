import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.middleware import RateLimitMiddleware, RequestIDMiddleware
from app.db import SessionLocal, engine, ensure_database_exists
from app.migrations import apply_sql_migrations
from app.modules.auth.router import router as auth_router
from app.modules.health.router import router as health_router
from app.modules.logtime.router import router as logtime_router
from app.modules.pull_requests.router import router as pull_requests_router
from app.modules.settings.router import router as settings_router
from app.modules.tickets.router import router as tickets_router
from app.modules.users.router import router as users_router
from app.modules.settings.service import ensure_system_settings

logger = logging.getLogger(__name__)


def bootstrap(db: Session) -> None:
    ensure_system_settings(db)


def wait_for_database(max_attempts: int = 30, sleep_seconds: float = 1.0) -> None:
    last_error: Exception | None = None
    ensure_database_exists()
    for _ in range(max_attempts):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except OperationalError as exc:
            last_error = exc
            time.sleep(sleep_seconds)
    if last_error:
        raise last_error


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Bootstrapping database")
    wait_for_database()
    apply_sql_migrations(engine)
    db = SessionLocal()
    try:
        bootstrap(db)
    finally:
        db.close()
    logger.info("Application bootstrap completed")
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Order: rate-limit first (cheap reject), then request-id (so all responses incl. 429 have it).
app.add_middleware(RateLimitMiddleware, max_requests=240, window_seconds=60, prefix_filter=settings.api_prefix)
app.add_middleware(RequestIDMiddleware)

app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(users_router, prefix=settings.api_prefix)
app.include_router(settings_router, prefix=settings.api_prefix)
app.include_router(tickets_router, prefix=settings.api_prefix)
app.include_router(logtime_router, prefix=settings.api_prefix)
app.include_router(pull_requests_router, prefix=settings.api_prefix)
