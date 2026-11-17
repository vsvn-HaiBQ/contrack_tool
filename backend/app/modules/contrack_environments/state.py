from __future__ import annotations

import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .config import EnvironmentError, EnvironmentSettings, contained


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def working_database_name(schema: str, run_id: str) -> str:
    version = re.sub(r"[^0-9a-z]", "", schema.lower())[:15] or "schema"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"ct_{version}_{stamp}_{run_id[-12:]}"


def write_atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            os.chmod(temporary, 0o600)
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as exc:
                # Windows scanners can briefly deny replacement of a recently read state file.
                # Retry only these Windows errors, with a strict 310 ms total bound.
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                    raise
                time.sleep(0.01 * (2 ** attempt))
    finally:
        temporary.unlink(missing_ok=True)


def write_yaml(path: Path, value: dict) -> None:
    write_atomic_text(path, yaml.safe_dump(value, allow_unicode=True, sort_keys=False))


def read_yaml(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise EnvironmentError(f"Invalid state YAML: {path}{location}. Repair the file or retain a backup before resetting tool-generated state.",
                               "INVALID_STATE_YAML", 500) from exc
    except UnicodeDecodeError as exc:
        raise EnvironmentError(f"Invalid state file encoding: {path}; expected UTF-8", "INVALID_STATE", 500) from exc
    if not isinstance(value, dict):
        raise EnvironmentError(f"Invalid persisted environment state: {path}; expected a YAML mapping", "INVALID_STATE", 500)
    return value


class EnvironmentLock:
    """OS-held lock: released on process exit, including crashes. Never unlink the inode."""

    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.path.stat().st_size == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise EnvironmentError("Environment preparation is already in progress.", "ENVIRONMENT_BUSY", 409) from exc
        self.file = handle
        return self

    def release(self):
        if self.file:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None

    @classmethod
    def busy(cls, path: Path) -> bool:
        if not path.exists():
            return False
        lock = cls(path)
        try:
            lock.acquire()
            return False
        except EnvironmentError as exc:
            if exc.code != "ENVIRONMENT_BUSY":
                raise
            return True
        finally:
            lock.release()


class RunHistoryService:
    def __init__(self, settings: EnvironmentSettings):
        self.settings = settings

    def directory(self, run_id: str) -> Path:
        if not re.fullmatch(r"\d{8}T\d{6}-[a-f0-9]{12}", run_id):
            raise EnvironmentError("Invalid run ID", "INVALID_RUN_ID")
        return contained(self.settings.path("runs"), run_id)

    def save(self, state):
        state["updated_at"] = now()
        write_yaml(self.directory(state["run_id"]) / "state.yaml", state)

    def log(self, run_id, step, message):
        path = self.directory(run_id) / "run.log"
        with path.open("a", encoding="utf-8") as output:
            os.chmod(path, 0o600)
            output.write(f"{now()} [{step}] {message}\n")

    def get(self, run_id: str, include_log=True) -> dict:
        directory = self.directory(run_id)
        state = read_yaml(directory / "state.yaml")
        if state is None:
            raise EnvironmentError("Run not found", "RUN_NOT_FOUND", 404)
        if state["status"] in ("QUEUED", "PREPARING") and not EnvironmentLock.busy(self.settings.path("lock")):
            state = {**state, "status": "INTERRUPTED", "error": {
                "code": "PROCESS_INTERRUPTED", "message": "Preparation process exited. Start a new preparation."}}
        if include_log:
            path = directory / "run.log"
            if path.is_file():
                with path.open("rb") as source:
                    source.seek(max(0, path.stat().st_size - 64 * 1024))
                    state["log"] = source.read().decode("utf-8", errors="replace")
            else:
                state["log"] = ""
            state["recipe"] = read_yaml(directory / "recipe.yaml")
            state["request"] = read_yaml(directory / "request.yaml")
        return state

    def list(self, limit=30, offset=0):
        root = self.settings.path("runs")
        directories = sorted((p.name for p in root.iterdir() if p.is_dir() and
                              re.fullmatch(r"\d{8}T\d{6}-[a-f0-9]{12}", p.name)), reverse=True) if root.exists() else []
        items = [self.get(run_id, include_log=False) for run_id in directories[offset:offset + limit]]
        return {"items": items, "total": len(directories), "limit": limit, "offset": offset}


class RuntimeStateService:
    def __init__(self, settings: EnvironmentSettings):
        self.settings = settings

    def get_current_environment(self):
        value = read_yaml(self.settings.path("current") / "version.yaml")
        if value and value.get("status") == "SWITCHING" and not EnvironmentLock.busy(self.settings.path("lock")):
            return {**value, "status": "UNKNOWN"}
        if value and value.get("status") == "RUNNING":
            # A crash between publishing runtime files and committing READY must not look successful.
            run_id = value.get("run_id", "")
            if not re.fullmatch(r"\d{8}T\d{6}-[a-f0-9]{12}", run_id):
                return {**value, "status": "UNKNOWN"}
            state = read_yaml(contained(self.settings.path("runs"), run_id) / "state.yaml")
            if not state or state.get("status") != "READY":
                return {**value, "status": "SWITCHING" if EnvironmentLock.busy(self.settings.path("lock")) else "UNKNOWN"}
        return value

    def save(self, value):
        current = self.settings.path("current")
        current.mkdir(parents=True, exist_ok=True)
        if value.get("status") == "RUNNING":
            write_atomic_text(current / "run-id", value["run_id"] + "\n")
        # Publish the authoritative state after its auxiliary pointer.
        write_yaml(current / "version.yaml", {**value, "updated_at": now()})
