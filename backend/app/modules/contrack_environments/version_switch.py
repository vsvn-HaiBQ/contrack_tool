"""Existing host Tomcat + Docker PostgreSQL switching through a restricted SSH runner."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from .catalog import StrictModel, VersionCatalogService, digest
from .config import EnvironmentError
from .state import EnvironmentLock, RunHistoryService, RuntimeStateService, now, read_yaml, working_database_name, write_atomic_text, write_yaml

logger = logging.getLogger(__name__)


class SwitchVersionRequest(StrictModel):
    war_id: str = Field(min_length=1, max_length=120)
    database_profile_id: str = Field(min_length=1, max_length=120)


class SSHHostRunner:
    def __init__(self, settings):
        self.settings = settings

    def configuration_error(self):
        config = self.settings.switch_version
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]*", config.ssh_host) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", config.ssh_user):
            return "Configure switch_version.ssh_host and ssh_user for the Linux host runner."
        if not shutil.which("ssh"):
            return "The backend image needs openssh-client; build with the switch-version Compose override."
        if not Path(config.private_key).is_file() or not Path(config.known_hosts).is_file():
            return "Mount the switch-version SSH private key and verified known_hosts file into the backend."
        return None

    def call(self, action, run_id=None):
        error = self.configuration_error()
        if error:
            raise EnvironmentError(error, "SWITCH_CONFIGURATION", 503)
        if action not in ("check", "run") or (action == "run" and not re.fullmatch(r"\d{8}T\d{6}-[a-f0-9]{12}", run_id or "")):
            raise EnvironmentError("Invalid host operation", "INVALID_HOST_OPERATION")
        config = self.settings.switch_version
        command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                   "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3",
                   "-p", str(config.ssh_port), "-i", config.private_key,
                   "-o", f"UserKnownHostsFile={config.known_hosts}",
                   f"{config.ssh_user}@{config.ssh_host}", action if run_id is None else f"run {run_id}"]
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=45 if action == "check" else config.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EnvironmentError("Host runner connection failed or timed out. Inspect the run history before retrying.", "HOST_CONNECTION_FAILED", 503) from exc
        try:
            value = json.loads(result.stdout)
            if not isinstance(value, dict):
                raise ValueError("Expected an object")
        except (ValueError, TypeError) as exc:
            raise EnvironmentError("Host runner did not return a valid result. Check SSH, the forced command and host configuration.", "HOST_CONNECTION_FAILED", 503) from exc
        if result.returncode or not value.get("ok"):
            # Only fixed runner error codes cross the trust boundary; never forward stderr or raw commands.
            code = value.get("code", "HOST_OPERATION_FAILED")
            if not isinstance(code, str) or not re.fullmatch(r"[A-Z_]{1,80}", code):
                code = "HOST_OPERATION_FAILED"
            raise EnvironmentError(f"Host runner failed ({code}). Check host configuration and the run history.", code, 503)
        return value


class VersionSwitchService:
    def __init__(self, settings, runner=None):
        self.settings = settings
        self.runner = runner or SSHHostRunner(settings)
        self.history = RunHistoryService(settings)
        self.runtime = RuntimeStateService(settings)

    def _enabled(self):
        if not self.settings.enabled or self.settings.operation_mode != "switch_version":
            raise EnvironmentError("Enable switch_version mode to switch WAR and database on the existing host.", "SWITCH_DISABLED", 409)

    def catalog(self):
        self._enabled()
        catalog = VersionCatalogService(self.settings, war_database_only=True)
        return {"wars": [{"id": war.war_id, "displayName": f"ConTrack {war.display_version} — {war.build_id}",
                          "filename": Path(war.artifact.file).name, "schema": war.compatibility.database_schema,
                          "status": war.status} for war in catalog.wars.values() if war.status == "available"],
                "databases": [{"id": db.database_id, "schema": db.schema_version, "profile": db.profile_type}
                              for db in catalog.databases.values() if db.status == "available"],
                "versions": [], "repositories": [], "configuration_error": self.runner.configuration_error()}

    def resolve(self, payload):
        self._enabled()
        catalog = VersionCatalogService(self.settings, war_database_only=True)
        war = catalog._available(catalog.wars, payload.war_id, "WAR")
        database = catalog._available(catalog.databases, payload.database_profile_id, "Database")
        if war.compatibility.database_schema != database.schema_version:
            raise EnvironmentError("WAR and baseline schema versions must match", "SCHEMA_MISMATCH")
        source = catalog.artifact_path(war, war.war_id)
        baseline = catalog.artifact_path(database, database.database_id)
        if source.suffix.lower() != ".war":
            raise EnvironmentError("WAR artifact must be a .war file", "INVALID_ARTIFACT")
        if baseline.suffix.lower() not in (".dump", ".backup"):
            raise EnvironmentError("Baseline must be a pg_dump custom archive (.dump or .backup)", "INVALID_ARTIFACT")
        recipe = {"operation_mode": "switch_version", "war": war.war_id,
                  "display_name": f"ConTrack {war.display_version} — {war.build_id}",
                  "database_baseline": database.database_id, "schema_version": database.schema_version,
                  "war_file": source.relative_to(self.settings.root.resolve()).as_posix(),
                  "baseline_file": baseline.relative_to(self.settings.root.resolve()).as_posix(),
                  "war_sha256": digest(source), "baseline_sha256": digest(baseline),
                  "repository_action": "unchanged"}
        current = self.runtime.get_current_environment()
        if current and current.get("status") in ("UNKNOWN", "SWITCHING"):
            raise EnvironmentError("Inspect and repair the interrupted deployment before starting another version switch.", "PREVIOUS_SWITCH_UNCERTAIN", 409)
        return recipe

    def _check_host(self):
        actual = self.runner.call("check")
        expected = {"root": str(self.settings.root.resolve()), **{key: str(getattr(self.settings, key))
                    for key in ("wars", "databases", "server", "runs", "current", "lock")}}
        if any(actual.get(key) != value for key, value in expected.items()):
            raise EnvironmentError("Backend and host runner must use the same root and managed paths.", "HOST_ROOT_MISMATCH")
        return actual

    def validate(self, payload):
        recipe = self.resolve(payload)
        actual = self._check_host()
        if Path(recipe["war_file"]).name != actual.get("war_filename"):
            raise EnvironmentError("Selected WAR filename must match war_filename in the host runner configuration.", "WAR_FILENAME_MISMATCH")
        return {"valid": True, "recipe": recipe}

    def _host_access(self, actual, directory):
        if os.name != "posix":
            return  # Windows is used only for local unit tests; the deployed backend is Linux.
        uid, gid = actual.get("uid"), actual.get("gid")
        if type(uid) is not int or type(gid) is not int or min(uid, gid) < 0:
            raise EnvironmentError("Host runner did not report its filesystem identity.", "HOST_IDENTITY_INVALID")
        current = self.settings.path("current")
        current.mkdir(parents=True, exist_ok=True, mode=0o700)
        paths = [self.settings.path("runs"), directory, current, self.settings.path("lock"),
                 *directory.iterdir(), current / "version.yaml", current / "run-id"]
        guard = self.settings.path("lock").with_name(self.settings.path("lock").name + ".host")
        paths.append(guard)
        for path in paths:
            if path.is_symlink():
                raise EnvironmentError("Tool state paths must not be symbolic links.", "INVALID_PATH")
            if path.exists():
                info = path.stat()
                if (info.st_uid, info.st_gid) != (uid, gid):
                    os.chown(path, uid, gid)

    def begin(self, payload, actor):
        self._enabled()
        lock = EnvironmentLock(self.settings.path("lock")).acquire()
        try:
            recipe = self.resolve(payload)
            actual = self._check_host()
            if Path(recipe["war_file"]).name != actual.get("war_filename"):
                raise EnvironmentError("Selected WAR filename must match war_filename in the host runner configuration.", "WAR_FILENAME_MISMATCH")
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:12]
            directory = self.history.directory(run_id)
            directory.mkdir(parents=True, mode=0o700)
            state = {"run_id": run_id, "operation_mode": "switch_version", "actor": actor,
                     "display_name": recipe["display_name"], "status": "QUEUED", "steps": {},
                     "working_database": working_database_name(recipe["schema_version"], run_id),
                     "created_at": now(), "failed_step": None, "error": None}
            recipe["working_database"] = state["working_database"]
            write_yaml(directory / "request.yaml", payload.model_dump())
            write_yaml(directory / "recipe.yaml", recipe)
            write_atomic_text(directory / "host-request.json", json.dumps({"recipe": recipe, "state": state}))
            self.history.save(state)
            self.history.log(run_id, "queued", "Host switch queued. A fresh working database will be restored; existing databases are retained.")
            # Files are private (0700/0600), but must be readable by the authenticated host runner,
            # which usually runs as vsvndev while the Docker backend runs as root.
            self._host_access(actual, directory)
            return state, lock
        except BaseException:
            lock.release()
            raise

    def execute(self, state, lock):
        try:
            self.runner.call("run", state["run_id"])
        except Exception:
            # The host owns progress and results. It may still hold its lock after SSH disconnects.
            logger.error("Host switch transport failed for run %s; check persisted host progress", state["run_id"])
            guard = self.settings.path("lock").with_name(self.settings.path("lock").name + ".host")
            if not EnvironmentLock._busy(guard, check_host=False):
                recorded = read_yaml(self.history.directory(state["run_id"]) / "state.yaml") or state
                if recorded.get("status") in ("QUEUED", "PREPARING"):
                    recorded.update(status="INTERRUPTED", error={"code": "HOST_CONNECTION_FAILED",
                                    "message": "Host switch interrupted. Inspect host progress and Tomcat before retrying."})
                    self.history.save(recorded)
        finally:
            lock.release()
