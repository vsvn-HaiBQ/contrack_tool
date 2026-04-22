from collections.abc import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def ensure_database_exists() -> None:
    url = make_url(settings.database_url)
    backend = url.get_backend_name()
    database_name = url.database
    if backend != "postgresql" or not database_name:
        return

    admin_engine = create_engine(
        url.set(database="postgres"),
        future=True,
        pool_pre_ping=True,
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": database_name},
            ).scalar()
            if exists:
                return
            quoted_name = database_name.replace('"', '""')
            connection.exec_driver_sql(f'CREATE DATABASE "{quoted_name}"')
    except OperationalError as exc:
        message = str(exc).lower()
        if "already exists" not in message:
            raise
    finally:
        admin_engine.dispose()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
