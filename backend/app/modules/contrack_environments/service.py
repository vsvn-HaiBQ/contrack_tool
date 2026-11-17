from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from .adapters import LinuxEnvironmentAdapter
from .catalog import PrepareRequest, VersionCatalogService, digest
from .config import EnvironmentError, EnvironmentSettings
from .state import EnvironmentLock, RunHistoryService, RuntimeStateService, now, read_yaml, working_database_name, write_yaml

logger = logging.getLogger(__name__)


class EnvironmentPreparationService:
    def __init__(self, settings: EnvironmentSettings, adapter=None):
        self.settings = settings
        self.adapter = adapter or LinuxEnvironmentAdapter(settings)
        self.history = RunHistoryService(settings)
        self.runtime = RuntimeStateService(settings)

    def _enabled(self):
        if not self.settings.enabled:
            raise EnvironmentError("Environment management is not configured. Ask an administrator to enable it.",
                                   "FEATURE_DISABLED", 503)

    def validate(self, request: PrepareRequest):
        self._enabled()
        recipe = VersionCatalogService(self.settings).resolve(request)
        self.adapter.preflight(recipe)
        return {"valid": True, "recipe": recipe.public()}

    def begin(self, request: PrepareRequest, actor: str):
        self._enabled()
        lock = EnvironmentLock(self.settings.path("lock")).acquire()
        try:
            # Immutable selections and input checks are resolved again under the switch lock.
            recipe = VersionCatalogService(self.settings).resolve(request)
            self.adapter.preflight(recipe)
            self._recover_interrupted()
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:12]
            database = working_database_name(recipe.database.schema_version, run_id)
            directory = self.history.directory(run_id)
            directory.mkdir(parents=True, mode=0o700)
            state = {
                "run_id": run_id, "bundle_id": recipe.bundle.bundle_id,
                "display_name": recipe.bundle.display_name, "actor": actor,
                "status": "QUEUED", "created_at": now(), "updated_at": now(),
                "steps": {}, "failed_step": None, "error": None,
                "working_database": database,
            }
            resolved = {**recipe.public(), "working_database": database,
                        "war_sha256": digest(recipe.war_path), "baseline_sha256": digest(recipe.baseline_path)}
            write_yaml(directory / "request.yaml", request.model_dump())
            write_yaml(directory / "recipe.yaml", resolved)
            self.history.save(state)
            self.history.log(run_id, "queued", "Preparation accepted; catalog artifacts will remain unchanged")
            return state, recipe, lock
        except BaseException:
            lock.release()
            raise

    def _recover_interrupted(self):
        root = self.settings.path("runs")
        if not root.exists():
            return
        for path in root.glob("*/state.yaml"):
            state = read_yaml(path)
            if state and state.get("status") in ("QUEUED", "PREPARING"):
                state.update(status="INTERRUPTED", error={"code": "PROCESS_INTERRUPTED",
                             "message": "Previous preparation process exited; working database is retained."})
                self.history.save(state)
                self.history.log(state["run_id"], "interrupted", "Previous preparation process exited")
        current = self.runtime.get_current_environment()
        if current and current.get("status") == "SWITCHING":
            self.runtime.save({**current, "status": "UNKNOWN"})

    def execute(self, state, recipe, lock):
        run_id = state["run_id"]
        database = state["working_database"]
        directory = self.history.directory(run_id)
        step = "validate"
        switched = False
        start_attempted = False

        def perform(name, operation):
            nonlocal step
            step = name
            state["steps"][name] = "RUNNING"
            self.history.save(state)
            self.history.log(run_id, name, "Started")
            result = operation()
            state["steps"][name] = "SUCCESS"
            self.history.save(state)
            self.history.log(run_id, name, "Completed")
            return result

        try:
            state["status"] = "PREPARING"
            self.history.save(state)
            recorded = read_yaml(directory / "recipe.yaml")

            def validate_snapshot():
                if digest(recipe.war_path) != recorded["war_sha256"] or digest(recipe.baseline_path) != recorded["baseline_sha256"]:
                    raise EnvironmentError("Catalog artifact changed after selection; start a new preparation", "CHECKSUM_MISMATCH")

            perform("validate", validate_snapshot)
            # Stage configuration and WAR before provisioning or interrupting the current application.
            perform("runtime_config", lambda: self.adapter.stage(recipe, database, directory))
            perform("database_create", lambda: self.adapter.create_database(database))
            perform("database_restore", lambda: self.adapter.restore_database(database, recipe.baseline_path))
            perform("database_schema", lambda: self.adapter.check_schema(database, recipe.database.schema_version))
            perform("repository_prepare", lambda: self.adapter.prepare_repository(recipe, directory))

            def stop_current():
                nonlocal switched
                previous = self.runtime.get_current_environment() or {}
                self.runtime.save({**previous, "status": "SWITCHING", "attempt_run_id": run_id})
                switched = True
                self.adapter.stop()

            perform("server_stop", stop_current)
            perform("war_deploy", lambda: self.adapter.deploy(recipe, directory))

            def start():
                nonlocal start_attempted
                start_attempted = True
                self.adapter.start()

            perform("server_start", start)
            health = perform("health_check", lambda: self.adapter.health(recipe, database))

            def publish():
                value = {**recipe.public(), "database": database, "run_id": run_id,
                         "status": "RUNNING", "health": health, "checked_at": now()}
                write_yaml(self.settings.path("server") / "state.yaml", value)
                write_yaml(self.settings.path("runtime_databases") / "current.yaml", {
                    "database": database, "baseline": recipe.database.database_id,
                    "schema_version": recipe.database.schema_version, "run_id": run_id,
                })
                write_yaml(self.settings.path("runtime_repositories") / "current.yaml", {
                    "repository": recipe.repository.repository_id, "run_id": run_id,
                })
                self.runtime.save(value)

            perform("runtime_state", publish)
            state.update(status="READY", health=health, completed_at=now())
            self.history.save(state)
            self.history.log(run_id, "ready", "Environment is ready; all six health checks passed")
        except Exception as exc:
            if not isinstance(exc, EnvironmentError):
                logger.error("Environment run %s failed at %s (%s)", run_id, step, type(exc).__name__)
            error = exc if isinstance(exc, EnvironmentError) else EnvironmentError(
                "Preparation failed unexpectedly; inspect server permissions and administrator configuration", "PREPARATION_FAILED")
            state["steps"][step] = "FAILED"
            state.update(status="FAILED", failed_step=step,
                         error={"code": error.code, "message": str(error)}, completed_at=now())
            # A failed candidate must not continue running after an unsuccessful health check.
            stopped = not start_attempted
            if start_attempted:
                try:
                    self.adapter.stop()
                    stopped = True
                except Exception:
                    stopped = False
            if switched:
                value = {**recipe.public(), "database": database, "run_id": run_id,
                         "status": "FAILED" if stopped and step != "server_stop" else "UNKNOWN"}
                try:
                    self.runtime.save(value)
                except Exception:
                    pass  # Persistent run failure below remains the source of truth.
            self.history.save(state)
            self.history.log(run_id, step, f"FAILED {error.code}: {error}")
        finally:
            lock.release()
