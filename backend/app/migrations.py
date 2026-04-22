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
    candidates = [
        _repo_root() / "sql",
        Path(__file__).resolve().parents[1] / "sql",
        Path.cwd() / "sql",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"Migration directory not found. Checked: {', '.join(str(path) for path in candidates)}")


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


def _existing_tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


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


def _apply_sql_file(engine: Engine, path: Path) -> None:
    script = path.read_text(encoding="utf-8")
    for statement in _split_sql_script(script):
        with engine.begin() as connection:
            connection.execute(text(statement))
    logger.info("Applied migration %s", path.stem)


def apply_sql_migrations(engine: Engine) -> None:
    ensure_schema_migrations_table(engine)
    existing_tables = _existing_tables(engine)
    init_schema_path = _migration_dir() / "001_init_schema.sql"
    if not INIT_SCHEMA_TABLES.issubset(existing_tables):
        logger.info("Core schema missing tables %s, applying 001_init_schema", sorted(INIT_SCHEMA_TABLES - existing_tables))
        _apply_sql_file(engine, init_schema_path)
        _mark_applied(engine, "001_init_schema")

    applied = _applied_versions(engine)
    for path in sorted(_migration_dir().glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        if version == "001_init_schema" and INIT_SCHEMA_TABLES.issubset(_existing_tables(engine)):
            logger.info("Skipping %s because core schema already exists", version)
            _mark_applied(engine, version)
            continue
        _apply_sql_file(engine, path)
        _mark_applied(engine, version)
