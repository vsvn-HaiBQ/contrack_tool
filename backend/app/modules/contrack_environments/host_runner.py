"""Standalone Python 3 host runner. No app imports, Docker socket mount or third-party packages.

Install as the forced command for a dedicated SSH key. See docs/contrack-version-switch.md.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import urlopen
import uuid
import xml.etree.ElementTree as ET

RUN_ID = re.compile(r"\d{8}T\d{6}-[a-f0-9]{12}")
DB_NAME = re.compile(r"ct_[a-z0-9_]{1,59}")


class RunnerError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def atomic(path, data, mode=0o600):
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as output:
            os.chmod(temporary, mode)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                    raise
                time.sleep(0.01 * (2 ** attempt))
    finally:
        temporary.unlink(missing_ok=True)


def save_json(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def inside(root, relative):
    part = Path(relative)
    if not relative or part.is_absolute() or ".." in part.parts or "\\" in relative or ":" in relative:
        raise RunnerError("INVALID_PATH")
    target = root / part
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()) or target.resolve() == root.resolve():
        raise RunnerError("INVALID_PATH")
    return target


@contextmanager
def file_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    acquired = False
    try:
        try:
            if os.name == "nt":
                import msvcrt
                if path.stat().st_size == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            raise RunnerError("ENVIRONMENT_BUSY") from exc
        yield
    finally:
        if acquired and os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


def is_locked(path):
    try:
        with file_lock(path):
            return False
    except RunnerError:
        return True


def jdbc_database(url, database):
    # Retain the host, port and all JDBC query options; replace only the DB name.
    match = re.fullmatch(r"(jdbc:postgresql://[^/\s]+/)([^?\s]+)(\?[^\s]*)?", url)
    if not match:
        raise RunnerError("JDBC_URL_UNSUPPORTED")
    return match[1] + database + (match[3] or "")


def change_jdbc(text, config, database):
    if config["format"] == "xml_resource":
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise RunnerError("JDBC_XML_INVALID") from exc
        resources = [node for node in root.iter() if node.tag == "Resource" and node.get("name") == config["resource_name"]]
        if len(resources) != 1 or not resources[0].get("url"):
            raise RunnerError("JDBC_RESOURCE_NOT_UNIQUE")
        old = resources[0].get("url")
        new = jdbc_database(old, database)
        # Edit the selected tag in place; retain comments, credentials and unrelated resources byte-for-byte.
        tags = list(re.finditer(r'''<Resource\b(?:[^>"']|"[^"]*"|'[^']*')*>''', text))
        matches = []
        for tag in tags:
            fragment = tag.group().rstrip()
            try:
                node = ET.fromstring(fragment if fragment.endswith("/>") else fragment[:-1] + "/>")
            except ET.ParseError:
                continue
            if node.get("name") == config["resource_name"]:
                matches.append(tag)
        if len(matches) != 1:
            raise RunnerError("JDBC_RESOURCE_NOT_UNIQUE")
        tag = matches[0]
        updated, count = re.subn(r'''(\burl\s*=\s*)(["'])(.*?)\2''',
                                 lambda match: match[1] + match[2] + html.escape(new, quote=True) + match[2],
                                 tag.group(), count=1, flags=re.S)
        if count != 1:
            raise RunnerError("JDBC_URL_UNSUPPORTED")
        return text[:tag.start()] + updated + text[tag.end():]
    if config["format"] == "properties":
        key = config["property"]
        pattern = re.compile(r"^(\s*" + re.escape(key) + r"\s*[=:]\s*)([^\r\n]*)(\r?)$", re.M)
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise RunnerError("JDBC_PROPERTY_NOT_UNIQUE")
        current = matches[0][2]
        escaped = current.startswith("jdbc\\:")
        if current.endswith("\\"):
            raise RunnerError("JDBC_MULTILINE_UNSUPPORTED")
        updated = jdbc_database(current.replace("\\:", ":"), database)
        if escaped:
            updated = updated.replace(":", "\\:")
        return pattern.sub(lambda match: match[1] + updated + match[3], text, count=1)
    raise RunnerError("JDBC_FORMAT_UNSUPPORTED")


class HostRunner:
    def __init__(self, config):
        self.config = config
        try:
            self.root = Path(config["root"]).resolve(strict=True)
            if not self.root.is_dir():
                raise ValueError()
            self.layout = {"root": str(self.root), **{key: config.get(key, default) for key, default in {
                "wars": "catalog/wars", "databases": "catalog/databases", "server": "runtime/server",
                "runs": "runs", "current": "runtime/current", "lock": "runtime/environment.lock"}.items()}}
            for key in self.layout:
                if key != "root":
                    inside(self.root, self.layout[key])
            self.server = inside(self.root, self.layout["server"])
            self.webapps = inside(self.server, "webapps")
            self.jdbc = inside(self.root, config["jdbc"]["file"])
            forbidden = [inside(self.root, self.layout[key]).resolve() for key in ("wars", "databases", "runs", "current")]
            if any(self.jdbc.resolve().is_relative_to(path) for path in [*forbidden, self.webapps.resolve()]):
                raise ValueError()
            if not self.jdbc.is_file() or not (self.server / "conf/server.xml").is_file() or not self.webapps.is_dir():
                raise ValueError()
            self.filename = config.get("war_filename", "app.war")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.war", self.filename) or ".." in self.filename:
                raise ValueError()
            self.target = inside(self.webapps, self.filename)
            if self.target.exists() and not self.target.is_file():
                raise ValueError()
            self.exploded = inside(self.webapps, self.filename[:-4])
            if self.exploded.exists() and not self.exploded.is_dir():
                raise ValueError()
            self.cwd = inside(self.root, config.get("command_cwd", self.layout["server"] + "/bin"))
            if not self.cwd.is_dir():
                raise ValueError()
            for key in ("stop_command", "start_command", *(["status_command"] if "status_command" in config else [])):
                command = config[key]
                if not isinstance(command, list) or not command or not all(isinstance(arg, str) and arg and "\0" not in arg for arg in command):
                    raise ValueError()
                if len(command) >= 2 and Path(command[0]).name in ("bash", "sh") and not command[1].startswith("-"):
                    script = Path(command[1])
                    if not (script if script.is_absolute() else self.cwd / script).is_file():
                        raise ValueError()
            self.pg = config["postgres"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.pg["container"]) or not self.pg["user"]:
                raise ValueError()
            query = config["schema_version_query"].strip().rstrip(";")
            if not query.lower().startswith("select ") or ";" in query:
                raise ValueError()
            self.schema_query = query
            health = urlsplit(config["health_url"])
            if health.scheme not in ("http", "https") or not health.hostname or health.username or health.password:
                raise ValueError()
            self.health_url = config["health_url"]
            self.server_host = config.get("server_host", "127.0.0.1")
            self.server_port = int(config.get("server_port", 8080))
            if not 1 <= self.server_port <= 65535:
                raise ValueError()
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise RunnerError("HOST_CONFIGURATION_INVALID") from exc

    def command(self, argv, *, source=None, timeout=None, capture=False):
        result = subprocess.run(argv, cwd=self.cwd, stdin=source, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=timeout or self.config.get("command_timeout", 900), check=False)
        if result.returncode:
            raise RunnerError("HOST_COMMAND_FAILED")
        return (result.stdout or b"").decode("utf-8").strip() if capture else None

    def pg_command(self, tool, args, **kwargs):
        return self.command(["docker", "exec", "-i", self.pg["container"], tool, *args], **kwargs)

    def sql(self, database, query):
        return self.pg_command("psql", ["-X", "-qAt", "--no-password", "-U", self.pg["user"], "--set=ON_ERROR_STOP=1",
                                       "--dbname=" + database, "--command=" + query], capture=True, timeout=30)

    def running(self):
        if "status_command" not in self.config:
            expected = ("-Dcatalina.base=" + str(self.server)).encode()
            for path in Path("/proc").glob("[0-9]*/cmdline"):
                try:
                    args = path.read_bytes().split(b"\0")
                    if expected in args and b"org.apache.catalina.startup.Bootstrap" in args:
                        return True
                except (OSError, PermissionError):
                    continue
            return False
        result = subprocess.run(self.config["status_command"], cwd=self.cwd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=15, check=False)
        if result.returncode == 0:
            return True
        if result.returncode in self.config.get("inactive_status_codes", [1, 3]):
            return False
        raise RunnerError("TOMCAT_STATUS_FAILED")

    def port_open(self):
        try:
            with socket.create_connection((self.server_host, self.server_port), timeout=1):
                return True
        except OSError:
            return False

    def stop(self):
        if self.running():
            self.command(self.config["stop_command"], timeout=120)
        deadline = time.monotonic() + self.config.get("stop_timeout", 60)
        while self.running() or self.port_open():
            if time.monotonic() >= deadline:
                raise RunnerError("TOMCAT_STOP_FAILED")
            time.sleep(1)

    def health(self, database=None):
        deadline = time.monotonic() + self.config.get("health_timeout", 120)
        while True:
            try:
                with urlopen(self.health_url, timeout=5) as response:
                    healthy = 200 <= response.status < 300
                if healthy and self.running() and self.port_open():
                    if database is None or int(self.sql(database,
                            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() AND backend_type = 'client backend'")) > 0:
                        return
            except (OSError, ValueError, RunnerError, subprocess.SubprocessError):
                pass
            if time.monotonic() >= deadline:
                raise RunnerError("APPLICATION_HEALTH_FAILED")
            time.sleep(2)

    def check(self):
        # Parse and validate the actual JDBC selector without writing any file.
        change_jdbc(self.jdbc.read_bytes().decode("utf-8"), self.config["jdbc"], "ct_preflight")
        if self.sql("postgres", "SELECT 1") != "1":
            raise RunnerError("POSTGRES_UNAVAILABLE")
        if not self.running() and self.port_open():
            raise RunnerError("TOMCAT_STATUS_MISMATCH")
        return {"ok": True, **self.layout, "war_filename": self.filename,
                "uid": os.getuid() if hasattr(os, "getuid") else 0,
                "gid": os.getgid() if hasattr(os, "getgid") else 0}

    def run(self, run_id):
        if not RUN_ID.fullmatch(run_id):
            raise RunnerError("INVALID_RUN_ID")
        lock = inside(self.root, self.layout["lock"])
        with file_lock(lock.with_name(lock.name + ".host")):
            # Never start a delayed SSH command after the backend has released its orchestration lock.
            if not is_locked(lock):
                raise RunnerError("ORCHESTRATOR_NOT_LOCKED")
            directory = inside(inside(self.root, self.layout["runs"]), run_id)
            request = json.loads((directory / "host-request.json").read_text(encoding="utf-8"))
            recipe, state = request["recipe"], request["state"]
            if state["run_id"] != run_id or not DB_NAME.fullmatch(state["working_database"]):
                raise RunnerError("INVALID_REQUEST")
            if recipe["working_database"] != state["working_database"]:
                raise RunnerError("INVALID_REQUEST")
            # An exclusive marker prevents replaying a stale SSH request, even after a crash.
            with (directory / "host-started").open("x") as marker:
                marker.write(stamp())
            self._execute(directory, recipe, state)
            return {"ok": state["status"] == "READY", "code": (state.get("error") or {}).get("code", "HOST_OPERATION_FAILED")}

    def _execute(self, directory, recipe, state):
        database = state["working_database"]
        step = "validate"
        touched = False
        was_running = False
        old_runtime = None
        old_pointer = None
        previous_war = False
        moved_exploded = False
        files_changed = False
        candidate_started = False
        backup = directory / "backup"
        current = inside(self.root, self.layout["current"])
        current.mkdir(parents=True, exist_ok=True)

        def persist():
            state["updated_at"] = stamp()
            save_json(directory / "state.yaml", state)  # JSON is also valid YAML.

        def log(name, message):
            with (directory / "run.log").open("a", encoding="utf-8") as output:
                os.chmod(directory / "run.log", 0o600)
                output.write(f"{stamp()} [{name}] {message}\n")

        def perform(name, operation):
            nonlocal step
            step = name
            state["steps"][name] = "RUNNING"
            persist()
            log(name, "Started")
            result = operation()
            state["steps"][name] = "SUCCESS"
            persist()
            log(name, "Completed")
            return result

        try:
            state["status"] = "PREPARING"
            persist()

            def validate():
                self.check()
                war = inside(inside(self.root, self.layout["wars"]),
                             Path(recipe["war_file"]).relative_to(self.layout["wars"]).as_posix())
                baseline = inside(inside(self.root, self.layout["databases"]),
                                  Path(recipe["baseline_file"]).relative_to(self.layout["databases"]).as_posix())
                if war.name != self.filename or sha256(war) != recipe["war_sha256"] or sha256(baseline) != recipe["baseline_sha256"]:
                    raise RunnerError("ARTIFACT_MISMATCH")
                return war, baseline

            war, baseline = perform("validate", validate)
            perform("database_create", lambda: self.pg_command("createdb", ["--no-password", "-U", self.pg["user"], "--template=template0", "--", database]))

            def restore():
                with baseline.open("rb") as source:
                    self.pg_command("pg_restore", ["--no-password", "-U", self.pg["user"], "--exit-on-error", "--single-transaction",
                                                   "--no-owner", "--no-privileges", "--no-tablespaces", "--dbname=" + database], source=source)
                if sha256(baseline) != recipe["baseline_sha256"]:
                    raise RunnerError("ARTIFACT_MISMATCH")

            perform("database_restore", restore)

            def schema():
                actual = self.sql(database, "BEGIN READ ONLY; SELECT * FROM (" + self.schema_query + ") AS ct_schema; COMMIT;")
                if actual != recipe["schema_version"]:
                    raise RunnerError("SCHEMA_MISMATCH")

            perform("database_schema", schema)

            def stage():
                backup.mkdir(mode=0o700)
                original = self.jdbc.read_bytes()
                updated = change_jdbc(original.decode("utf-8"), self.config["jdbc"], database).encode("utf-8")
                atomic(backup / "jdbc.original", original)
                atomic(directory / "jdbc.staged", updated)
                shutil.copyfile(war, directory / "war.staged")
                os.chmod(directory / "war.staged", 0o600)
                if sha256(directory / "war.staged") != recipe["war_sha256"]:
                    raise RunnerError("ARTIFACT_MISMATCH")

            perform("stage", stage)
            was_running = self.running()

            def stop():
                nonlocal touched, old_runtime, old_pointer, previous_war
                old_runtime = (current / "version.yaml").read_bytes() if (current / "version.yaml").exists() else None
                old_pointer = (current / "run-id").read_bytes() if (current / "run-id").exists() else None
                if old_runtime is not None:
                    atomic(backup / "previous-version.yaml", old_runtime)
                save_json(current / "version.yaml", {"status": "SWITCHING", "operation_mode": "switch_version", "attempt_run_id": state["run_id"]})
                touched = True
                self.stop()
                if self.jdbc.read_bytes() != (backup / "jdbc.original").read_bytes():
                    raise RunnerError("JDBC_CHANGED_DURING_SWITCH")
                previous_war = self.target.is_file()
                if previous_war:
                    shutil.copyfile(self.target, backup / "previous.war")
                    os.chmod(backup / "previous.war", 0o600)

            perform("server_stop", stop)

            def deploy():
                nonlocal moved_exploded, files_changed
                files_changed = True
                atomic(self.jdbc, (directory / "jdbc.staged").read_bytes(), self.jdbc.stat().st_mode & 0o777)
                # Move the exploded application outside webapps so Tomcat rebuilds it from the selected WAR.
                if self.exploded.exists():
                    self.exploded.rename(backup / "exploded")
                    moved_exploded = True
                self.replace_war(directory / "war.staged", self.target)

            perform("war_deploy", deploy)
            def start():
                nonlocal candidate_started
                candidate_started = True
                self.command(self.config["start_command"], timeout=120)

            perform("server_start", start)
            perform("health_check", lambda: self.health(database))

            def publish():
                if self.jdbc.read_bytes() != (directory / "jdbc.staged").read_bytes():
                    raise RunnerError("JDBC_CHANGED_DURING_SWITCH")
                atomic(current / "run-id", (state["run_id"] + "\n").encode())
                save_json(current / "version.yaml", {"operation_mode": "switch_version", "status": "RUNNING",
                    "display_name": recipe["display_name"], "war": recipe["war"], "database": database,
                    "database_baseline": recipe["database_baseline"], "schema_version": recipe["schema_version"],
                    "repository": "existing", "run_id": state["run_id"], "checked_at": stamp(),
                    "health": {"http": True, "process": True, "port": True, "database_connection": True}})

            perform("runtime_state", publish)
            state.update(status="READY", completed_at=stamp())
            persist()
            log("ready", "WAR and fresh working database switched successfully. Existing databases are retained.")
        except Exception as exc:
            code = exc.code if isinstance(exc, RunnerError) else "HOST_OPERATION_FAILED"
            state["steps"][step] = "FAILED"
            state.update(status="FAILED", failed_step=step, error={"code": code,
                         "message": f"Host switch failed at {step}. Inspect host configuration and this run's backups."}, completed_at=stamp())
            log(step, f"FAILED {code} [{type(exc).__name__}]; candidate database retained")
            if touched:
                try:
                    self.stop()
                    if files_changed:
                        atomic(self.jdbc, (backup / "jdbc.original").read_bytes(), self.jdbc.stat().st_mode & 0o777)
                        if previous_war:
                            self.replace_war(backup / "previous.war", self.target)
                        else:
                            self.target.unlink(missing_ok=True)
                        if (moved_exploded or candidate_started) and self.exploded.exists():
                            self.exploded.rename(directory / "failed-exploded")
                    if moved_exploded:
                        (backup / "exploded").rename(self.exploded)
                    if was_running:
                        self.command(self.config["start_command"], timeout=120)
                        self.health()
                    if old_runtime is not None:
                        atomic(current / "version.yaml", old_runtime)
                    else:
                        save_json(current / "version.yaml", {"status": "RESTORED", "operation_mode": "switch_version"})
                    if old_pointer is not None:
                        atomic(current / "run-id", old_pointer)
                    else:
                        (current / "run-id").unlink(missing_ok=True)
                    state["rollback_status"] = "SUCCESS"
                    log("rollback", "Previous deployment restored; server health checked if it was previously running.")
                except Exception:
                    state["rollback_status"] = "FAILED"
                    save_json(current / "version.yaml", {"status": "UNKNOWN", "operation_mode": "switch_version", "attempt_run_id": state["run_id"]})
                    log("rollback", "FAILED; inspect Tomcat and restore backups manually before retrying")
            persist()

    @staticmethod
    def replace_war(source, target):
        if target.is_symlink():
            raise RunnerError("INVALID_PATH")
        temporary = target.with_name(".ct-switch-" + uuid.uuid4().hex + ".tmp")
        try:
            with source.open("rb") as incoming, temporary.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
                os.chmod(temporary, 0o644)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("action", choices=("check", "run", "serve"))
    parser.add_argument("run_id", nargs="?")
    args = parser.parse_args()
    try:
        action, run_id = args.action, args.run_id
        if action == "serve":
            parts = shlex.split(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
            if parts == ["check"]:
                action, run_id = "check", None
            elif len(parts) == 2 and parts[0] == "run" and RUN_ID.fullmatch(parts[1]):
                action, run_id = parts
            else:
                raise RunnerError("INVALID_HOST_OPERATION")
        config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
        runner = HostRunner(config)
        result = runner.check() if action == "check" else runner.run(run_id or "")
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    except Exception as exc:
        print(json.dumps({"ok": False, "code": exc.code if isinstance(exc, RunnerError) else "HOST_OPERATION_FAILED"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
