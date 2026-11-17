from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

from .catalog import digest, repository_address
from .config import EnvironmentError, EnvironmentSettings, contained
from .state import write_yaml


class LinuxEnvironmentAdapter:
    def __init__(self, settings: EnvironmentSettings):
        self.settings = settings

    def _tool(self, name):
        return str(Path(self.settings.pg_bin) / name) if self.settings.pg_bin else name

    def _pg_env(self):
        env = os.environ.copy()
        for key in ("PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGPASSWORD", "PGPASSFILE"):
            env.pop(key, None)
        env.update(PGHOST=self.settings.pg_host, PGPORT=str(self.settings.pg_port),
                   PGUSER=self.settings.pg_user, PGCONNECT_TIMEOUT="5", PGAPPNAME="contrack-environments")
        if self.settings.pg_password.get_secret_value():
            env["PGPASSWORD"] = self.settings.pg_password.get_secret_value()
        if self.settings.pg_passfile:
            env["PGPASSFILE"] = self.settings.pg_passfile
        return env

    def _command(self, argv, *, env=None):
        try:
            result = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", shell=False,
                                    timeout=self.settings.command_timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EnvironmentError("External tool could not complete; check server-side installation and connectivity",
                                   "EXTERNAL_TOOL_FAILED") from exc
        if result.returncode:
            # Tool output can contain passwords, JDBC strings or source data. Never persist it.
            raise EnvironmentError("External tool failed; verify database credentials, baseline format and server configuration",
                                   "EXTERNAL_TOOL_FAILED")
        return result.stdout.strip()

    def preflight(self, recipe):
        if os.name != "posix":
            raise EnvironmentError("Environment preparation requires a Linux host", "LINUX_REQUIRED", 503)
        for tool in ("createdb", "pg_restore", "psql"):
            if not shutil.which(self._tool(tool)):
                raise EnvironmentError(f"Required PostgreSQL tool is missing: {tool}", "TOOL_MISSING", 503)
        if not self.settings.schema_version_query.strip():
            raise EnvironmentError("Administrator must configure the real application schema-version query",
                                   "SCHEMA_QUERY_REQUIRED", 503)
        for script in ("startup.sh", "shutdown.sh"):
            if not self.settings.tomcat_home or not (Path(self.settings.tomcat_home) / "bin" / script).is_file():
                raise EnvironmentError("Administrator must configure an installed Tomcat home", "TOMCAT_CONFIG", 503)
        self._templates()
        repository_address(recipe.repository)
        url = urlsplit(self.settings.health_url)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise EnvironmentError("Invalid application health URL", "HEALTH_CONFIG", 503)
        if url.hostname != self.settings.server_host or (url.port or (443 if url.scheme == "https" else 80)) != self.settings.server_port:
            raise EnvironmentError("Health URL must address the configured managed Tomcat host and port", "HEALTH_CONFIG", 503)
        if self._port_open() and not self._managed_pid():
            raise EnvironmentError("Application port belongs to an unmanaged process; no process was stopped",
                                   "UNMANAGED_SERVER", 409)

    def _templates(self):
        root = Path(self.settings.config_templates) if self.settings.config_templates else None
        if not root or not root.is_dir() or not (root / "server.xml").is_file():
            raise EnvironmentError("A dedicated Tomcat conf template directory with server.xml is required", "TEMPLATE_CONFIG", 503)
        files = list(root.rglob("*"))
        if any(p.is_symlink() for p in files):
            raise EnvironmentError("Configuration templates must not contain symbolic links", "TEMPLATE_CONFIG")
        combined = "\n".join(p.read_text(encoding="utf-8") for p in files if p.is_file())
        if "{{DATABASE_NAME}}" not in combined or "{{REPOSITORY_URL}}" not in combined:
            raise EnvironmentError("Templates must bind DATABASE_NAME and REPOSITORY_URL", "TEMPLATE_CONFIG")
        return root

    def create_database(self, name):
        self._command([self._tool("createdb"), "--no-password", "--template=template0", "--", name], env=self._pg_env())

    def restore_database(self, name, baseline):
        self._command([self._tool("pg_restore"), "--no-password", "--exit-on-error", "--single-transaction",
                       "--no-owner", "--no-privileges", f"--dbname={name}", "--", str(baseline)], env=self._pg_env())

    def check_schema(self, database, expected):
        env = self._pg_env()
        env["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=10000"
        actual = self._command([self._tool("psql"), "--no-password", "--no-psqlrc", "--tuples-only", "--no-align",
                                "--set=ON_ERROR_STOP=1", f"--dbname={database}",
                                "--command", self.settings.schema_version_query], env=env)
        if actual != expected:
            raise EnvironmentError("Restored database schema does not match the selected WAR", "SCHEMA_MISMATCH")

    def prepare_repository(self, recipe, run_directory):
        host, port = repository_address(recipe.repository)
        try:
            with socket.create_connection((host, port), timeout=5):
                pass
        except OSError as exc:
            raise EnvironmentError("Selected repository server is unreachable", "REPOSITORY_UNREACHABLE") from exc
        write_yaml(run_directory / "repository.yaml", {
            "repository_id": recipe.repository.repository_id, "repository_type": recipe.repository.repository_type,
            "url": recipe.repository.url,
        })

    def stage(self, recipe, database, run_directory):
        root = self._templates()
        stage = run_directory / "staged-conf"
        stage.mkdir(mode=0o700)
        values = {
            "DATABASE_NAME": database, "DATABASE_HOST": self.settings.pg_host,
            "DATABASE_PORT": str(self.settings.pg_port), "DATABASE_USER": self.settings.pg_user,
            "REPOSITORY_URL": recipe.repository.url, "SERVER_PORT": str(self.settings.server_port),
            "JDBC_URL": f"jdbc:postgresql://{self.settings.pg_host}:{self.settings.pg_port}/{quote(database)}",
        }
        for source in root.rglob("*"):
            if source.is_dir():
                continue
            target = contained(stage, source.relative_to(root).as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            text = source.read_text(encoding="utf-8")
            for key, value in values.items():
                # XML templates need escaped attribute values; properties templates use literal URLs.
                if source.suffix.lower() == ".xml":
                    from xml.sax.saxutils import escape
                    value = escape(value, {'"': "&quot;", "'": "&apos;"})
                text = text.replace("{{" + key + "}}", value)
            if re.search(r"\{\{[A-Z_]+\}\}", text):
                raise EnvironmentError("Unresolved configuration template placeholder", "TEMPLATE_CONFIG")
            target.write_text(text, encoding="utf-8")
            os.chmod(target, 0o600)
        try:
            tree = ET.parse(stage / "server.xml")
            ports = [int(c.get("port", "0")) for c in tree.findall(".//Connector")]
            if self.settings.server_port not in ports:
                raise ValueError("Configured connector missing")
        except (ET.ParseError, ValueError) as exc:
            raise EnvironmentError("Tomcat server.xml must contain the configured application port", "TEMPLATE_CONFIG") from exc
        snapshot = run_directory / "contrack.war"
        shutil.copyfile(recipe.war_path, snapshot)
        if digest(snapshot) != digest(recipe.war_path):
            raise EnvironmentError("WAR changed while creating runtime snapshot", "CHECKSUM_MISMATCH")

    def _tomcat_env(self):
        env = os.environ.copy()
        env.update(CATALINA_HOME=self.settings.tomcat_home, CATALINA_BASE=str(self.settings.path("server")),
                   CATALINA_PID=str(self.settings.path("server") / "tomcat.pid"))
        return env

    def _managed_pid(self):
        pidfile = self.settings.path("server") / "tomcat.pid"
        try:
            pid = int(pidfile.read_text().strip())
            if pid <= 1:
                return None
            command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            expected = f"-Dcatalina.base={self.settings.path('server')}".encode()
            if expected not in command or b"org.apache.catalina.startup.Bootstrap" not in command:
                return None
            os.kill(pid, 0)
            return pid
        except (ValueError, OSError):
            return None

    def _port_open(self):
        try:
            with socket.create_connection((self.settings.server_host, self.settings.server_port), timeout=1):
                return True
        except OSError:
            return False

    def stop(self):
        if not self._managed_pid():
            if self._port_open():
                raise EnvironmentError("Refusing to stop an unmanaged server", "UNMANAGED_SERVER")
            return
        self._command(["/bin/sh", str(Path(self.settings.tomcat_home) / "bin/shutdown.sh")], env=self._tomcat_env())
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if not self._managed_pid() and not self._port_open():
                return
            time.sleep(0.5)
        raise EnvironmentError("Managed Tomcat did not stop within 30 seconds", "SERVER_STOP_FAILED")

    def deploy(self, recipe, run_directory):
        base = self.settings.path("server")
        # Only alter the dedicated managed base, never CATALINA_HOME or a shared Tomcat.
        for name in ("webapps", "conf", "logs", "temp", "work"):
            contained(base, name).mkdir(parents=True, exist_ok=True)
        for name in ("contrack", "contrack.war"):
            target = contained(base, "webapps/" + name)
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
        conf = contained(base, "conf")
        if any(p.is_symlink() for p in conf.rglob("*")):
            raise EnvironmentError("Managed Tomcat conf must not contain symbolic links", "INVALID_PATH")
        shutil.rmtree(conf)
        shutil.copytree(run_directory / "staged-conf", conf)
        shutil.copyfile(run_directory / "contrack.war", contained(base, "webapps/contrack.war"))

    def start(self):
        pidfile = self.settings.path("server") / "tomcat.pid"
        if self._managed_pid() or self._port_open():
            raise EnvironmentError("Application process or port is already in use", "SERVER_START_FAILED")
        pidfile.unlink(missing_ok=True)
        self._command(["/bin/sh", str(Path(self.settings.tomcat_home) / "bin/startup.sh")], env=self._tomcat_env())

    def health(self, recipe, database):
        deadline = time.monotonic() + self.settings.health_timeout
        while time.monotonic() < deadline:
            if self._managed_pid() and self._port_open():
                try:
                    with urlopen(self.settings.health_url, timeout=3) as response:
                        # Redirects/login forms must not mask an error at another host or port.
                        ok = response.status == 200 and response.geturl() == self.settings.health_url
                    if ok:
                        deployed = contained(self.settings.path("server"), "webapps/contrack.war")
                        if digest(deployed) != digest(recipe.war_path):
                            raise EnvironmentError("Deployed WAR checksum mismatch", "HEALTH_CHECK_FAILED")
                        self.check_schema(database, recipe.database.schema_version)
                        return {"process": True, "port": True, "war": True, "database": True,
                                "schema": True, "application": True}
                except (OSError, ValueError):
                    pass
            time.sleep(1)
        raise EnvironmentError("Application health check failed; inspect the managed Tomcat logs", "HEALTH_CHECK_FAILED")
