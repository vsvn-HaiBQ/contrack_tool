"""Copy a catalog WAR into an existing Tomcat without changing its configuration or database."""
from __future__ import annotations

import os
from os import replace as replace_war
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from .catalog import StrictModel, VersionCatalogService, digest
from .config import EnvironmentError, EnvironmentSettings, contained
from .state import EnvironmentLock, RunHistoryService, RuntimeStateService, now, read_yaml, write_yaml


class DeployWarRequest(StrictModel):
    war_id: str = Field(min_length=1, max_length=120)


class WarDeploymentService:
    def __init__(self, settings: EnvironmentSettings):
        self.settings = settings
        self.history = RunHistoryService(settings)
        self.runtime = RuntimeStateService(settings)

    def _enabled(self):
        if not self.settings.enabled or self.settings.operation_mode != "deploy_war":
            raise EnvironmentError("Enable deploy_war mode in the administrator configuration to use this operation",
                                   "DEPLOY_WAR_DISABLED", 409)

    def catalog(self):
        return VersionCatalogService(self.settings, wars_only=True)

    @staticmethod
    def display_name(war):
        return f"ConTrack {war.display_version} — {war.build_type} / {war.build_id}"

    def _resolve(self, payload):
        self._enabled()
        catalog = self.catalog()
        war = catalog._available(catalog.wars, payload.war_id, "WAR")
        source = catalog.artifact_path(war, war.war_id)
        if source.suffix.lower() != ".war":
            raise EnvironmentError("WAR artifact must be a .war file", "INVALID_ARTIFACT")
        base = self.settings.path("server")
        conf = contained(base, "conf")
        webapps = contained(base, "webapps")
        if not (conf / "server.xml").is_file() or not webapps.is_dir():
            raise EnvironmentError("Existing Tomcat needs conf/server.xml and a webapps directory in runtime/server",
                                   "EXISTING_TOMCAT_REQUIRED")
        target = webapps / "contrack.war"
        # Require a literal destination, not a symlink into another application or directory.
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise EnvironmentError("Tomcat WAR destination must be a regular file", "INVALID_PATH")
        if source == target.resolve():
            raise EnvironmentError("Catalog WAR and runtime WAR must be separate files", "INVALID_PATH")
        return war, source, target

    def list_wars(self):
        self._enabled()
        catalog = self.catalog()
        items = []
        for war in catalog.wars.values():
            if war.status != "available":
                continue
            error = None
            try:
                self._resolve(DeployWarRequest(war_id=war.war_id))
            except EnvironmentError as exc:
                error = str(exc)
            items.append({"id": war.war_id, "displayName": self.display_name(war),
                          "schema": war.compatibility.database_schema,
                          "status": "invalid" if error else "available", "error": error})
        return items

    def validate(self, payload):
        war, _, _ = self._resolve(payload)
        return {"valid": True, "operation_mode": "deploy_war", "war_id": war.war_id,
                "display_name": self.display_name(war), "destination": f"{self.settings.server}/webapps/contrack.war"}

    def begin(self, payload, actor):
        self._enabled()
        lock = EnvironmentLock(self.settings.path("lock")).acquire()
        try:
            war, source, _ = self._resolve(payload)
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:12]
            directory = self.history.directory(run_id)
            directory.mkdir(parents=True, mode=0o700)
            recipe = {
                "operation_mode": "deploy_war", "war": war.war_id, "display_name": self.display_name(war),
                "schema_version": war.compatibility.database_schema, "war_sha256": digest(source),
                "destination": f"{self.settings.server}/webapps/contrack.war",
                "configuration": "existing", "database_action": "unchanged", "repository_action": "unchanged",
            }
            state = {"run_id": run_id, "operation_mode": "deploy_war", "bundle_id": None,
                     "war_id": war.war_id, "display_name": recipe["display_name"], "actor": actor,
                     "working_database": None, "status": "QUEUED", "created_at": now(), "steps": {},
                     "failed_step": None, "error": None}
            write_yaml(directory / "request.yaml", payload.model_dump())
            write_yaml(directory / "recipe.yaml", recipe)
            self.history.save(state)
            self.history.log(run_id, "queued", "WAR copy queued; existing Tomcat configuration and DB/repository bindings are retained")
            return state, source, lock
        except BaseException:
            lock.release()
            raise

    def execute(self, state, source: Path, lock):
        run_id = state["run_id"]
        directory = self.history.directory(run_id)
        staged = None
        step = "validate"
        copied = False
        switching = False
        previous = None
        try:
            state["status"] = "PREPARING"
            self.history.save(state)
            recipe = read_yaml(directory / "recipe.yaml")
            _, current_source, target = self._resolve(DeployWarRequest(war_id=state["war_id"]))
            if source != current_source or digest(source) != recipe["war_sha256"]:
                raise EnvironmentError("Catalog WAR changed after selection; start a new deployment", "CHECKSUM_MISMATCH")
            state["steps"][step] = "SUCCESS"
            self.history.save(state)
            step = "war_copy"
            state["steps"][step] = "RUNNING"
            self.history.save(state)
            self.history.log(run_id, step, "Copying WAR to existing Tomcat webapps")
            # A non-.war temporary file prevents Tomcat from picking up a partially copied artifact.
            staged = contained(target.parent, f".contrack-{uuid.uuid4().hex}.tmp")
            with source.open("rb") as incoming, staged.open("xb") as outgoing:
                os.chmod(staged, 0o644)
                shutil.copyfileobj(incoming, outgoing)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if digest(staged) != recipe["war_sha256"]:
                raise EnvironmentError("WAR copy checksum mismatch", "CHECKSUM_MISMATCH")
            if target.is_symlink():
                raise EnvironmentError("Tomcat WAR destination changed during deployment", "INVALID_PATH")
            # A process crash at the rename boundary must not leave an old RUNNING state published.
            previous = self.runtime.get_current_environment()
            self.runtime.save({**(previous or {}), "operation_mode": "deploy_war", "status": "SWITCHING",
                               "attempt_run_id": run_id, "application_status": "NOT_CHECKED"})
            switching = True
            replace_war(staged, target)
            copied = True
            state["steps"][step] = "SUCCESS"
            state.update(status="DEPLOYED", completed_at=now(), application_status="NOT_CHECKED")
            self.history.save(state)
            self.runtime.save({"operation_mode": "deploy_war", "war": state["war_id"],
                               "display_name": state["display_name"], "run_id": run_id,
                               "status": "DEPLOYED", "application_status": "NOT_CHECKED",
                               "destination": recipe["destination"], "copied_at": now()})
            self.history.log(run_id, step, "WAR copied. Application reload/restart is controlled by the existing Tomcat setup; application health was not checked.")
        except Exception as exc:
            error = exc if isinstance(exc, EnvironmentError) else EnvironmentError(
                "WAR deployment failed; check runtime storage permissions and free disk space", "WAR_DEPLOY_FAILED")
            state["steps"][step] = "FAILED"
            state.update(status="FAILED", failed_step=step, error={"code": error.code, "message": str(error)},
                         war_copied=copied, completed_at=now())
            self.history.save(state)
            if copied:
                self.runtime.save({"operation_mode": "deploy_war", "war": state["war_id"],
                                   "run_id": run_id, "status": "UNKNOWN", "application_status": "NOT_CHECKED"})
            elif switching:
                self.runtime.save(previous or {"operation_mode": "deploy_war", "status": "NOT_PREPARED"})
            self.history.log(run_id, step, f"FAILED {error.code}: {error}")
        finally:
            try:
                if staged is not None:
                    staged.unlink(missing_ok=True)
            finally:
                lock.release()
