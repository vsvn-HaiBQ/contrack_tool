from __future__ import annotations

from pathlib import Path
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)
INIT_SCHEMA_TABLES = {
    "users",
    "user_settings",
    "system_settings",
    "managed_tickets",
    "ticket_links",
    "audit_logs",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _migration_dir() -> Path:
    return _repo_root() / "sql"


def ensure_schema_migrations_table(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(50) PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )


def _applied_versions(engine: Engine) -> set[str]:
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT version FROM schema_migrations"))
        return {row[0] for row in rows}


def _mark_applied(engine: Engine, version: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO schema_migrations(version) VALUES (:version) ON CONFLICT (version) DO NOTHING"), {"version": version})


def _split_sql_script(script: str) -> list[str]:
    statements = []
    current: list[str] = []
    inside_dollar_block = False
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        current.append(line)
        dollar_count = line.count("$$")
        if dollar_count % 2 == 1:
            inside_dollar_block = not inside_dollar_block
        if stripped.endswith(";") and not inside_dollar_block:
            statements.append("\n".join(current).strip())
            current = []
    if current:
        statements.append("\n".join(current).strip())
    return statements


def apply_sql_migrations(engine: Engine) -> None:
    ensure_schema_migrations_table(engine)
    applied = _applied_versions(engine)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for path in sorted(_migration_dir().glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        if version == "001_init_schema" and INIT_SCHEMA_TABLES.issubset(existing_tables):
            logger.info("Skipping %s because core schema already exists", version)
            _mark_applied(engine, version)
            continue
        script = path.read_text(encoding="utf-8")
        for statement in _split_sql_script(script):
            with engine.begin() as connection:
                connection.execute(text(statement))
        logger.info("Applied migration %s", version)
        _mark_applied(engine, version)
