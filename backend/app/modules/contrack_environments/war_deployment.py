"""Copy a catalog WAR into an existing Tomcat without changing its configuration or database."""
from __future__ import annotations

import os
import errno
import logging
from os import replace as replace_war
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from .catalog import StrictModel, VersionCatalogService, digest
from .config import EnvironmentError, EnvironmentSettings, contained
from .state import EnvironmentLock, RunHistoryService, RuntimeStateService, now, read_yaml, write_yaml

logger = logging.getLogger(__name__)


def storage_error(exc: Exception, operation: str, copied: bool = False) -> EnvironmentError:
    """Report actionable filesystem failures without echoing exception arguments or credentials."""
    number = getattr(exc, "errno", None)
    failures = {
        errno.EACCES: ("WAR_PERMISSION_DENIED", "Permission denied; check the backend UID/GID, directory permissions and ACLs"),
        errno.EPERM: ("WAR_PERMISSION_DENIED", "Operation not permitted; check ownership, ACLs and filesystem restrictions"),
        errno.ENOSPC: ("WAR_STORAGE_FULL", "No space left on device; check free bytes and inodes on the runtime filesystem"),
        getattr(errno, "EDQUOT", 122): ("WAR_QUOTA_EXCEEDED", "Filesystem quota exceeded"),
        errno.EROFS: ("WAR_READ_ONLY", "Runtime filesystem is read-only; check the Docker bind mount and host filesystem"),
        errno.ENOENT: ("WAR_PATH_NOT_FOUND", "Source, destination or temporary file no longer exists"),
        errno.ENOTDIR: ("WAR_INVALID_PATH", "A required directory is a file"),
        errno.EISDIR: ("WAR_INVALID_PATH", "A WAR file path is a directory"),
        errno.EBUSY: ("WAR_DESTINATION_BUSY", "Destination is busy or individually bind-mounted; inspect its mount before replacing it"),
        errno.EXDEV: ("WAR_CROSS_DEVICE", "Atomic replacement crossed filesystem boundaries"),
        errno.EIO: ("WAR_STORAGE_IO_ERROR", "Filesystem I/O error; inspect host storage"),
    }
    if isinstance(exc, PermissionError) and number is None:
        number = errno.EACCES
    code, detail = failures.get(number, ("WAR_DEPLOY_FAILED", "Deployment operation failed; inspect the server filesystem and run log"))
    symbol = errno.errorcode.get(number, type(exc).__name__)
    suffix = "; WAR was already copied, but deployment bookkeeping failed" if copied else ""
    return EnvironmentError(f"{operation}: {detail} [{symbol}]{suffix}", code)


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
        if source.suffix.lower() != ".war" or Path(war.artifact.file).suffix.lower() != ".war":
            raise EnvironmentError("WAR artifact must be a .war file", "INVALID_ARTIFACT")
        base = self.settings.path("server")
        conf = contained(base, "conf")
        webapps = contained(base, "webapps")
        if not (conf / "server.xml").is_file() or not webapps.is_dir():
            raise EnvironmentError("Existing Tomcat needs conf/server.xml and a webapps directory in runtime/server",
                                   "EXISTING_TOMCAT_REQUIRED")
        target = webapps / Path(war.artifact.file).name
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
                          "filename": Path(war.artifact.file).name,
                          "destination": f"{self.settings.server}/webapps/{Path(war.artifact.file).name}",
                          "schema": war.compatibility.database_schema,
                          "status": "invalid" if error else "available", "error": error})
        return items

    def validate(self, payload):
        war, _, target = self._resolve(payload)
        self.runtime.get_current_environment()
        return {"valid": True, "operation_mode": "deploy_war", "war_id": war.war_id,
                "display_name": self.display_name(war), "source_file": war.artifact.file,
                "destination": f"{self.settings.server}/webapps/{target.name}"}

    def begin(self, payload, actor):
        self._enabled()
        lock = EnvironmentLock(self.settings.path("lock")).acquire()
        try:
            war, source, target = self._resolve(payload)
            # Validate existing bookkeeping before copying a potentially large WAR.
            self.runtime.get_current_environment()
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:12]
            directory = self.history.directory(run_id)
            directory.mkdir(parents=True, mode=0o700)
            recipe = {
                "operation_mode": "deploy_war", "war": war.war_id, "display_name": self.display_name(war),
                "schema_version": war.compatibility.database_schema, "war_sha256": digest(source),
                "source_file": war.artifact.file,
                "destination": f"{self.settings.server}/webapps/{target.name}",
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
        operation = "record deployment progress"
        try:
            state["status"] = "PREPARING"
            self.history.save(state)
            recipe = read_yaml(directory / "recipe.yaml")
            _, current_source, target = self._resolve(DeployWarRequest(war_id=state["war_id"]))
            if source != current_source or digest(source) != recipe["war_sha256"] or \
                    f"{self.settings.server}/webapps/{target.name}" != recipe["destination"]:
                raise EnvironmentError("Catalog WAR or destination changed after selection; start a new deployment", "CHECKSUM_MISMATCH")
            state["steps"][step] = "SUCCESS"
            self.history.save(state)
            step = "war_copy"
            state["steps"][step] = "RUNNING"
            self.history.save(state)
            self.history.log(run_id, step, f"Copying {recipe['source_file']} to {recipe['destination']}")
            # A non-.war temporary file prevents Tomcat from picking up a partially copied artifact.
            staged = contained(target.parent, f".contrack-{uuid.uuid4().hex}.tmp")
            operation = "open catalog WAR"
            with source.open("rb") as incoming:
                operation = "create temporary WAR in webapps"
                with staged.open("xb") as outgoing:
                    operation = "set temporary WAR permissions"
                    os.chmod(staged, 0o644)
                    operation = "copy WAR bytes"
                    shutil.copyfileobj(incoming, outgoing)
                    operation = "flush temporary WAR"
                    outgoing.flush()
                    operation = "sync temporary WAR to storage"
                    os.fsync(outgoing.fileno())
            operation = "verify temporary WAR checksum"
            if digest(staged) != recipe["war_sha256"]:
                raise EnvironmentError("WAR copy checksum mismatch", "CHECKSUM_MISMATCH")
            if target.is_symlink():
                raise EnvironmentError("Tomcat WAR destination changed during deployment", "INVALID_PATH")
            # A process crash at the rename boundary must not leave an old RUNNING state published.
            operation = "read current deployment state"
            previous = self.runtime.get_current_environment()
            operation = "save switching state"
            self.runtime.save({**(previous or {}), "operation_mode": "deploy_war", "status": "SWITCHING",
                               "attempt_run_id": run_id, "application_status": "NOT_CHECKED"})
            switching = True
            operation = "replace runtime WAR"
            replace_war(staged, target)
            copied = True
            operation = "save deployment result"
            state["steps"][step] = "SUCCESS"
            state.update(status="DEPLOYED", completed_at=now(), application_status="NOT_CHECKED")
            self.history.save(state)
            self.runtime.save({"operation_mode": "deploy_war", "war": state["war_id"],
                               "display_name": state["display_name"], "run_id": run_id,
                               "status": "DEPLOYED", "application_status": "NOT_CHECKED",
                               "source_file": recipe["source_file"], "destination": recipe["destination"], "copied_at": now()})
            self.history.log(run_id, step, "WAR copied. Application reload/restart is controlled by the existing Tomcat setup; application health was not checked.")
        except Exception as exc:
            error = exc if isinstance(exc, EnvironmentError) else storage_error(exc, operation, copied)
            state["steps"][step] = "FAILED"
            state.update(status="FAILED", failed_step=step, error={"code": error.code, "message": str(error)},
                         failed_operation=operation, war_copied=copied, completed_at=now())
            # Storage failures may also prevent state/log writes. Keep a sanitized server log in that case.
            logger.error("WAR run %s failed: %s: %s", run_id, error.code, error)
            try:
                self.history.save(state)
                if copied:
                    self.runtime.save({"operation_mode": "deploy_war", "war": state["war_id"],
                                       "run_id": run_id, "status": "UNKNOWN", "application_status": "NOT_CHECKED"})
                elif switching:
                    self.runtime.save(previous or {"operation_mode": "deploy_war", "status": "NOT_PREPARED"})
                self.history.log(run_id, step, f"FAILED {error.code}: {error}")
            except OSError:
                logger.error("WAR run %s could not persist failure details; filesystem unavailable", run_id)
        finally:
            try:
                if staged is not None:
                    try:
                        staged.unlink(missing_ok=True)
                    except OSError:
                        logger.error("WAR run %s could not remove its temporary WAR; inspect webapps", run_id)
            finally:
                lock.release()
