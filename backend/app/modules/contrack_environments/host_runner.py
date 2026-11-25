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
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import uuid
import xml.etree.ElementTree as ET

RUN_ID = re.compile(r"\d{8}T\d{6}-[a-f0-9]{12}")
DB_NAME = re.compile(r"ct_[a-z0-9_]{1,59}")


class RunnerError(Exception):
    def __init__(self, code, *, line=None, column=None, field=None, stop_status=None, health_status=None):
        self.code = code
        self.line = line
        self.column = column
        self.field = field
        self.stop_status = stop_status
        self.health_status = health_status
        super().__init__(code)


def stop_diagnostic(exc):
    status = getattr(exc, "stop_status", None)
    if isinstance(status, dict) and type(status.get("process_running")) is bool and type(status.get("port_open")) is bool:
        return f" (process_running={status['process_running']}, configured_port_open={status['port_open']})"
    return ""


def health_diagnostic(exc):
    status = getattr(exc, "health_status", None)
    if not isinstance(status, dict):
        return ""
    # Never log exception text, response bodies, redirect URLs or connection credentials.
    safe = {key: status[key] for key in ("healthy", "process_running", "configured_port_open")
            if type(status.get(key)) is bool}
    if type(status.get("http_status")) is int and 100 <= status["http_status"] <= 599:
        safe["http_status"] = status["http_status"]
    for key, allowed in {
        "http_error": {"TLS_CERTIFICATE_INVALID", "TLS_ERROR", "CONNECTION_REFUSED", "TIMEOUT",
                       "NAME_RESOLUTION_FAILED", "HTTP_ERROR", "NETWORK_ERROR", "INVALID_RESPONSE"},
        "process_error": {"TOMCAT_STATUS_FAILED"},
        "database_status": {"not_requested", "waiting_for_readiness", "connected", "no_client_connection", "query_failed"},
    }.items():
        if isinstance(status.get(key), str) and status[key] in allowed:
            safe[key] = status[key]
    return " " + json.dumps(safe, sort_keys=True) if safe else ""


def load_host_config(path):
    """Report setup errors without exposing config contents, credentials or exception arguments."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise RunnerError("HOST_CONFIG_NOT_FOUND") from exc
    except PermissionError as exc:
        raise RunnerError("HOST_CONFIG_PERMISSION_DENIED") from exc
    except UnicodeError as exc:
        raise RunnerError("HOST_CONFIG_INVALID_UTF8") from exc
    except OSError as exc:
        raise RunnerError("HOST_CONFIG_READ_FAILED") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RunnerError("HOST_CONFIG_INVALID_JSON", line=exc.lineno, column=exc.colno) from exc
    if not isinstance(value, dict):
        raise RunnerError("HOST_CONFIG_NOT_OBJECT")
    return value


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
        field = "root"
        try:
            self.root = Path(config["root"]).resolve(strict=True)
            if not self.root.is_dir():
                raise ValueError()
            self.layout = {"root": str(self.root), **{key: config.get(key, default) for key, default in {
                "wars": "catalog/wars", "databases": "catalog/databases", "server": "runtime/server",
                "runs": "runs", "current": "runtime/current", "lock": "runtime/environment.lock"}.items()}}
            for key in self.layout:
                if key != "root":
                    field = key
                    inside(self.root, self.layout[key])
            field = "server"
            self.server = inside(self.root, self.layout["server"])
            field = "server.webapps"
            self.webapps = inside(self.server, "webapps")
            if not self.webapps.is_dir():
                raise ValueError()
            field = "server.conf.server_xml"
            if not (self.server / "conf/server.xml").is_file():
                raise ValueError()
            field = "jdbc.file"
            self.jdbc = inside(self.root, config["jdbc"]["file"])
            forbidden = [inside(self.root, self.layout[key]).resolve() for key in ("wars", "databases", "runs", "current")]
            if any(self.jdbc.resolve().is_relative_to(path) for path in [*forbidden, self.webapps.resolve()]):
                raise ValueError()
            if not self.jdbc.is_file():
                raise ValueError()
            field = "jdbc.format"
            if config["jdbc"]["format"] not in ("xml_resource", "properties"):
                raise ValueError()
            field = "jdbc.resource_name" if config["jdbc"]["format"] == "xml_resource" else "jdbc.property"
            selector = config["jdbc"].get(field.split(".")[1])
            if not isinstance(selector, str) or not selector:
                raise ValueError()
            field = "war_filename"
            self.filename = config.get("war_filename", "app.war")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.war", self.filename) or ".." in self.filename:
                raise ValueError()
            self.target = inside(self.webapps, self.filename)
            if self.target.exists() and not self.target.is_file():
                raise ValueError()
            self.exploded = inside(self.webapps, self.filename[:-4])
            if self.exploded.exists() and not self.exploded.is_dir():
                raise ValueError()
            field = "command_cwd"
            self.cwd = inside(self.root, config.get("command_cwd", self.layout["server"] + "/bin"))
            if not self.cwd.is_dir():
                raise ValueError()
            for key in ("stop_command", "start_command", *(["status_command"] if "status_command" in config else [])):
                field = key
                command = config[key]
                if not isinstance(command, list) or not command or not all(isinstance(arg, str) and arg and "\0" not in arg for arg in command):
                    raise ValueError()
                if len(command) >= 2 and Path(command[0]).name in ("bash", "sh") and not command[1].startswith("-"):
                    script = Path(command[1])
                    if not (script if script.is_absolute() else self.cwd / script).is_file():
                        raise ValueError()
            field = "postgres.container"
            self.pg = config["postgres"]
            if not isinstance(self.pg["container"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.pg["container"]):
                raise ValueError()
            field = "postgres.user"
            if not isinstance(self.pg["user"], str) or not self.pg["user"]:
                raise ValueError()
            field = "schema_version_query"
            query = config.get("schema_version_query")
            if query is None:
                query = ""
            if not isinstance(query, str):
                raise ValueError()
            query = query.strip()
            if query:
                query = query.rstrip(";")
                if not query.lower().startswith("select ") or ";" in query:
                    raise ValueError()
            self.schema_query = query
            field = "health_url"
            health = urlsplit(config["health_url"])
            if health.scheme not in ("http", "https") or not health.hostname or health.username or health.password:
                raise ValueError()
            self.health_url = config["health_url"]
            field = "health_ca_file"
            self.health_context = None
            ca_file = config.get("health_ca_file")
            if ca_file not in (None, ""):
                if not isinstance(ca_file, str):
                    raise ValueError()
                ca_path = Path(ca_file)
                if health.scheme != "https" or not ca_path.is_absolute() or not ca_path.is_file():
                    raise ValueError()
                # Trust this explicitly configured certificate/CA while retaining hostname verification.
                self.health_context = ssl.create_default_context(cafile=str(ca_path))
            self.server_host = config.get("server_host", "127.0.0.1")
            field = "server_port"
            self.server_port = int(config.get("server_port", 8080))
            if not 1 <= self.server_port <= 65535:
                raise ValueError()
        except RunnerError as exc:
            if exc.field is None:
                exc.field = field
            raise
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise RunnerError("HOST_CONFIGURATION_INVALID", field=field) from exc

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
        while True:
            process_running, port_open = self.running(), self.port_open()
            if not process_running and not port_open:
                return
            if time.monotonic() >= deadline:
                raise RunnerError("TOMCAT_STOP_FAILED", stop_status={"process_running": process_running, "port_open": port_open})
            time.sleep(1)

    def http_connector_ports(self):
        """Resolve static HTTP(S) connector ports. Leave dynamic property-based ports unguessed."""
        try:
            server = ET.parse(self.server / "conf/server.xml").getroot()
        except ET.ParseError as exc:
            raise RunnerError("TOMCAT_SERVER_XML_INVALID", field="server.conf.server_xml") from exc
        try:
            offset = int(server.get("portOffset", "0"))
        except ValueError:
            return None
        ports = []
        for connector in server.iter("Connector"):
            if "ajp" in connector.get("protocol", "").lower():
                continue
            try:
                port = int(connector.get("port", ""))
            except ValueError:
                return None
            if port <= 0:
                return None
            ports.append(port + offset)
        return sorted(set(ports)) or None

    def health_probe(self, database=None):
        """One read-only readiness probe, with bounded diagnostics that contain no secrets."""
        status = {"healthy": False, "http_status": None, "http_error": None,
                  "process_running": None, "process_error": None,
                  "configured_port_open": self.port_open(),
                  "database_status": "not_requested" if database is None else "waiting_for_readiness"}
        try:
            status["process_running"] = self.running()
        except (OSError, RunnerError, subprocess.SubprocessError):
            status["process_error"] = "TOMCAT_STATUS_FAILED"
        try:
            options = {"context": self.health_context} if self.health_context is not None else {}
            with urlopen(self.health_url, timeout=5, **options) as response:
                status["http_status"] = response.status
        except HTTPError as exc:
            status["http_status"] = exc.code
            status["http_error"] = "HTTP_ERROR"
            exc.close()
        except (OSError, ValueError) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            if isinstance(reason, ssl.SSLCertVerificationError):
                status["http_error"] = "TLS_CERTIFICATE_INVALID"
            elif isinstance(reason, ssl.SSLError):
                status["http_error"] = "TLS_ERROR"
            elif isinstance(reason, ConnectionRefusedError):
                status["http_error"] = "CONNECTION_REFUSED"
            elif isinstance(reason, TimeoutError):
                status["http_error"] = "TIMEOUT"
            elif isinstance(reason, socket.gaierror):
                status["http_error"] = "NAME_RESOLUTION_FAILED"
            else:
                status["http_error"] = "INVALID_RESPONSE" if isinstance(exc, ValueError) else "NETWORK_ERROR"
        http_status = status["http_status"]
        ready = (status["http_error"] is None and isinstance(http_status, int) and 200 <= http_status < 300
                 and status["process_running"] is True and status["configured_port_open"])
        if ready and database is not None:
            try:
                count = int(self.sql(database,
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() AND backend_type = 'client backend'"))
                status["database_status"] = "connected" if count > 0 else "no_client_connection"
            except (OSError, ValueError, RunnerError, subprocess.SubprocessError):
                status["database_status"] = "query_failed"
            ready = status["database_status"] == "connected"
        status["healthy"] = bool(ready)
        return status

    def health(self, database=None):
        deadline = time.monotonic() + self.config.get("health_timeout", 120)
        while True:
            status = self.health_probe(database)
            if status["healthy"]:
                return
            if time.monotonic() >= deadline:
                raise RunnerError("APPLICATION_HEALTH_FAILED", health_status=status)
            time.sleep(2)

    def parallel_apps(self):
        """Find parallel deployments of this same context; other contexts are not managed."""
        prefix = self.filename[:-4] + "##"
        descriptors = self.server / "conf/Catalina/localhost"
        if any(path.is_file() for path in descriptors.glob(prefix + "*.xml")):
            raise RunnerError("PARALLEL_CONTEXT_DESCRIPTOR")
        matches = []
        for path in self.webapps.iterdir():
            if path.name.startswith(prefix) and len(path.name) > len(prefix) and (path.is_dir() or path.name.endswith(".war")):
                if any(ord(char) < 32 for char in path.name):
                    raise RunnerError("PARALLEL_DEPLOYMENT_UNSAFE")
                matches.append(inside(self.webapps, path.name))
        return sorted(matches, key=lambda path: path.name)

    def check(self):
        ports = self.http_connector_ports()
        if ports is not None and self.server_port not in ports:
            raise RunnerError("HOST_CONFIGURATION_INVALID", field="server_port")
        # Parse and validate the actual JDBC selector without writing any file.
        change_jdbc(self.jdbc.read_bytes().decode("utf-8"), self.config["jdbc"], "ct_preflight")
        if self.sql("postgres", "SELECT 1") != "1":
            raise RunnerError("POSTGRES_UNAVAILABLE")
        if not self.running() and self.port_open():
            raise RunnerError("TOMCAT_STATUS_MISMATCH")
        return {"ok": True, **self.layout, "war_filename": self.filename,
                "schema_verification": "query" if self.schema_query else "manifest_only",
                "parallel_deployments": [path.name for path in self.parallel_apps()],
                "http_connector_ports": ports,
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

    def recover_stop(self):
        """Local-admin recovery only: archive an uncertain record when no application files changed."""
        lock = inside(self.root, self.layout["lock"])
        with file_lock(lock.with_name(lock.name + ".host")), file_lock(lock):
            self.check()
            if self.running() or self.port_open():
                raise RunnerError("RECOVERY_TOMCAT_NOT_STOPPED")
            current = inside(inside(self.root, self.layout["current"]), "version.yaml")
            if not current.exists():
                return {"ok": True, "recovery": "not_required"}
            try:
                value = json.loads(current.read_text(encoding="utf-8"))
                run_id = value.get("attempt_run_id", "")
                if value.get("status") != "UNKNOWN" or not RUN_ID.fullmatch(run_id):
                    raise ValueError()
                directory = inside(inside(self.root, self.layout["runs"]), run_id)
                state = json.loads((directory / "state.yaml").read_text(encoding="utf-8"))
                if state.get("operation_mode") != "switch_version" or state.get("status") != "FAILED" or \
                        state.get("failed_step") != "server_stop" or "war_deploy" in state.get("steps", {}) or \
                        state.get("deployment_started") is True:
                    raise ValueError()
                if self.jdbc.read_bytes() != (directory / "backup/jdbc.original").read_bytes():
                    raise RunnerError("RECOVERY_JDBC_CHANGED")
                # The stage must still contain the known candidate; this is not recovery of a partially deployed run.
                recipe = json.loads((directory / "host-request.json").read_text(encoding="utf-8"))["recipe"]
                if sha256(directory / "war.staged") != recipe["war_sha256"]:
                    raise ValueError()
                if (directory / "backup/exploded").exists() or (directory / "backup/parallel-webapps").exists():
                    raise ValueError()
            except RunnerError:
                raise
            except (KeyError, TypeError, ValueError, AttributeError, OSError) as exc:
                raise RunnerError("RECOVERY_NOT_ALLOWED") from exc
            saved = current.with_name(f"version.failed-stop-{run_id}-{uuid.uuid4().hex[:8]}.yaml.bak")
            current.rename(saved)
            # Keep the failed history, candidate DB and all backups. Do not manufacture a RUNNING/READY record.
            return {"ok": True, "recovery": "unmodified_stop_failure_archived", "run_id": run_id,
                    "state_backup": saved.relative_to(self.root).as_posix()}

    def recover_rollback(self):
        """Record a verified file rollback after its final health check previously failed."""
        lock = inside(self.root, self.layout["lock"])
        with file_lock(lock.with_name(lock.name + ".host")), file_lock(lock):
            current = inside(inside(self.root, self.layout["current"]), "version.yaml")
            try:
                original = current.read_bytes()
                value = json.loads(original)
                if value.get("status") == "RESTORED" and value.get("rollback_recovery") is True:
                    return {"ok": True, "recovery": "not_required", "run_id": value.get("attempt_run_id")}
                run_id = value.get("attempt_run_id", "")
                if value.get("status") != "UNKNOWN" or not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
                    raise ValueError()
                directory = inside(inside(self.root, self.layout["runs"]), run_id)
                backup = inside(directory, "backup")
                state = json.loads((directory / "state.yaml").read_text(encoding="utf-8"))
                request = json.loads((directory / "host-request.json").read_text(encoding="utf-8"))
                recipe = request["recipe"]
                if state.get("run_id") != run_id or request["state"].get("run_id") != run_id or \
                        state.get("operation_mode") != "switch_version" or state.get("status") != "FAILED" or \
                        state.get("failed_step") != "health_check" or state.get("rollback_status") != "FAILED" or \
                        (state.get("error") or {}).get("code") != "APPLICATION_HEALTH_FAILED" or \
                        any(state.get("steps", {}).get(step) != "SUCCESS" for step in ("stage", "server_stop", "war_deploy", "server_start")) or \
                        state.get("steps", {}).get("health_check") != "FAILED" or \
                        Path(recipe["war_file"]).name != self.filename or \
                        sha256(directory / "war.staged") != recipe["war_sha256"]:
                    raise ValueError()
                # Support existing runs: this error is logged only after all file restores and start completed.
                rollback_lines = [line for line in (directory / "run.log").read_text(encoding="utf-8").splitlines()
                                  if " [rollback] " in line]
                if not rollback_lines or not re.search(
                        r" \[rollback\] FAILED APPLICATION_HEALTH_FAILED(?:[ ;]|$)", rollback_lines[-1]):
                    raise ValueError()
                expected_parallel = recipe.get("parallel_deployments", [])
                if not isinstance(expected_parallel, list) or any(not isinstance(name, str) for name in expected_parallel) or \
                        state.get("archived_parallel_deployments", []) != expected_parallel:
                    raise ValueError()
                original_jdbc = (backup / "jdbc.original").read_bytes()
                previous_war = backup / "previous.war"
                old_war_hash = sha256(previous_war) if previous_war.is_file() else None
            except (KeyError, TypeError, ValueError, AttributeError, OSError) as exc:
                raise RunnerError("RECOVERY_NOT_ALLOWED") from exc

            def verify_restored_files():
                if self.jdbc.read_bytes() != original_jdbc:
                    raise RunnerError("RECOVERY_JDBC_CHANGED")
                if (old_war_hash is None and self.target.exists()) or \
                        (old_war_hash is not None and (not self.target.is_file() or sha256(self.target) != old_war_hash)):
                    raise RunnerError("RECOVERY_WAR_CHANGED")
                parallel_backup = backup / "parallel-webapps"
                actual = {path.name for path in self.parallel_apps()}
                expected = set(expected_parallel)
                # A restored versioned WAR may have been exploded by Tomcat since restart.
                allowed = expected | {name[:-4] for name in expected if name.endswith(".war")}
                if (backup / "exploded").exists() or (parallel_backup.exists() and any(parallel_backup.iterdir())) or \
                        not expected.issubset(actual) or not actual.issubset(allowed):
                    raise RunnerError("RECOVERY_WEBAPPS_NOT_RESTORED")

            self.check()
            verify_restored_files()
            if not self.running() or not self.port_open():
                raise RunnerError("RECOVERY_TOMCAT_NOT_RUNNING")
            self.health()  # Verify HTTPS, process and port; do not claim candidate DB verification.
            verify_restored_files()
            if current.read_bytes() != original:
                raise RunnerError("RECOVERY_STATE_CHANGED")
            recovered_at = stamp()
            saved = current.with_name(f"version.failed-rollback-{run_id}-{uuid.uuid4().hex[:8]}.yaml.bak")
            atomic(saved, original)
            state["updated_at"] = recovered_at
            state["rollback_recovery"] = {"status": "VERIFIED", "verified_at": recovered_at,
                                          "database_connection": "not_checked",
                                          "state_backup": saved.relative_to(self.root).as_posix()}
            save_json(directory / "state.yaml", state)
            with (directory / "run.log").open("a", encoding="utf-8") as output:
                os.chmod(directory / "run.log", 0o600)
                output.write(f"{recovered_at} [rollback_recovery] Restored WAR/JDBC/parallel apps and application health verified; "
                             "recording RESTORED, database connection not checked. Failed run, candidate DB and backups retained.\n")
            save_json(current, {"status": "RESTORED", "operation_mode": "switch_version",
                                "display_name": "Restored previous deployment", "attempt_run_id": run_id,
                                "rollback_recovery": True, "checked_at": recovered_at,
                                "health": {"http": True, "process": True, "port": True, "database_connection": None}})
            return {"ok": True, "recovery": "rollback_verified", "run_id": run_id,
                    "current_status": "RESTORED", "database_connection": "not_checked",
                    "state_backup": saved.relative_to(self.root).as_posix()}

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
        parallel_moved = []
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
                mode = "query" if self.schema_query else "manifest_only"
                if recipe.get("schema_verification", mode) != mode:
                    raise RunnerError("HOST_CONFIGURATION_CHANGED")
                if recipe.get("parallel_deployments", []) != [path.name for path in self.parallel_apps()]:
                    raise RunnerError("PARALLEL_DEPLOYMENTS_CHANGED")
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

            if self.schema_query:
                perform("database_schema", schema)
                state["schema_verified"] = True
            else:
                state["steps"]["database_schema"] = "SKIPPED"
                state["schema_verified"] = False
                persist()
                log("database_schema", "SKIPPED: schema_version_query is not configured; compatibility is based on catalog manifests.")

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
                if recipe.get("parallel_deployments", []) != [path.name for path in self.parallel_apps()]:
                    raise RunnerError("PARALLEL_DEPLOYMENTS_CHANGED")
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
                # A versioned app##... would otherwise take precedence over the selected app.war.
                # Archive matching WARs/directories reversibly, only after Tomcat is stopped.
                for path in self.parallel_apps():
                    saved = backup / "parallel-webapps"
                    saved.mkdir(mode=0o700, exist_ok=True)
                    path.rename(saved / path.name)
                    parallel_moved.append(path.name)
                    log("parallel_archive", "Archived " + path.name)
                state["archived_parallel_deployments"] = parallel_moved.copy()
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
                    "schema_verified": state["schema_verified"],
                    "archived_parallel_deployments": parallel_moved.copy(),
                    "repository": "existing", "run_id": state["run_id"], "checked_at": stamp(),
                    "health": {"http": True, "process": True, "port": True, "database_connection": True,
                               "schema_verified": state["schema_verified"]}})

            perform("runtime_state", publish)
            state.update(status="READY", completed_at=stamp())
            persist()
            log("ready", "WAR and fresh working database switched successfully. Existing databases are retained.")
        except Exception as exc:
            code = exc.code if isinstance(exc, RunnerError) else "HOST_OPERATION_FAILED"
            state["steps"][step] = "FAILED"
            detail = stop_diagnostic(exc) + health_diagnostic(exc)
            state.update(status="FAILED", failed_step=step, deployment_started=files_changed, error={"code": code,
                         "message": f"Host switch failed at {step}{detail}. Inspect host configuration and this run's backups."}, completed_at=stamp())
            log(step, f"FAILED {code} [{type(exc).__name__}]{detail}; candidate database retained")
            if not files_changed:
                log(step, "Runtime WAR/JDBC and webapps have not been modified by this run.")
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
                    for name in reversed(parallel_moved):
                        original = inside(self.webapps, name)
                        if original.exists():
                            failed = directory / "failed-parallel-webapps"
                            failed.mkdir(mode=0o700, exist_ok=True)
                            original.rename(failed / name)
                        (backup / "parallel-webapps" / name).rename(original)
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
                except Exception as rollback_exc:
                    state["rollback_status"] = "FAILED"
                    save_json(current / "version.yaml", {"status": "UNKNOWN", "operation_mode": "switch_version", "attempt_run_id": state["run_id"]})
                    rollback_code = rollback_exc.code if isinstance(rollback_exc, RunnerError) else "HOST_OPERATION_FAILED"
                    log("rollback", f"FAILED {rollback_code}{stop_diagnostic(rollback_exc)}{health_diagnostic(rollback_exc)}; inspect Tomcat and restore backups manually before retrying")
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
    parser.add_argument("action", choices=("check", "run", "serve", "recover-stop", "recover-rollback", "diagnose-health"))
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
        config = load_host_config(args.config)
        runner = HostRunner(config)
        if action == "check":
            result = runner.check()
        elif action == "diagnose-health":
            status = runner.health_probe()
            result = {"ok": status["healthy"], "health": status,
                      "custom_ca": runner.health_context is not None}
        elif action == "recover-stop":
            result = runner.recover_stop()
        elif action == "recover-rollback":
            result = runner.recover_rollback()
        else:
            result = runner.run(run_id or "")
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    except Exception as exc:
        result = {"ok": False, "code": exc.code if isinstance(exc, RunnerError) else "HOST_OPERATION_FAILED"}
        if isinstance(exc, RunnerError) and exc.line is not None:
            result.update(line=exc.line, column=exc.column)
        if isinstance(exc, RunnerError) and exc.field is not None:
            result["field"] = exc.field
        print(json.dumps(result))
        return 1


if __name__ == "__main__":
    sys.exit(main())
