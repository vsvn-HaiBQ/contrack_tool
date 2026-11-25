import json
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_contrack_environments import EnvironmentTestCase
from app.modules.contrack_environments.config import EnvironmentError
from app.modules.contrack_environments.host_runner import HostRunner, RunnerError, change_jdbc, file_lock, load_host_config
from app.modules.contrack_environments.state import EnvironmentLock, read_yaml, write_yaml
from app.modules.contrack_environments.version_switch import SSHHostRunner, SwitchVersionRequest, VersionSwitchService


class SimulatedHost(HostRunner):
    """Use real file switching, locks and state; simulate only external PostgreSQL/Tomcat."""
    def __init__(self, config):
        super().__init__(config)
        self.active = True
        self.calls = []
        self.databases = {"existing_db": "5.2.0"}
        self.failure = None

    def running(self): return self.active
    def port_open(self): return self.active

    def command(self, argv, *, source=None, **kwargs):
        if argv == self.config["stop_command"]:
            self.calls.append("stop")
            if self.failure == "stop":
                raise RunnerError("TOMCAT_STOP_FAILED")
            self.active = False
        elif argv == self.config["start_command"]:
            self.calls.append("start")
            if self.failure == "start":
                self.failure = None
                raise RunnerError("TOMCAT_START_FAILED")
            self.active = True
        elif argv[:3] == ["docker", "exec", "-i"]:
            tool = argv[4]
            self.calls.append(tool)
            if self.failure == tool:
                raise RunnerError("HOST_COMMAND_FAILED")
            if tool == "createdb":
                if argv[-1] in self.databases:
                    raise AssertionError("Must create a fresh database")
                self.databases[argv[-1]] = None
            elif tool == "pg_restore":
                database = next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--dbname="))
                self.databases[database] = source.read().decode()
                assert "--single-transaction" in argv and "--exit-on-error" in argv
                assert "--no-owner" in argv and "--no-privileges" in argv
        else:
            raise AssertionError(argv)

    def sql(self, database, query):
        if query == "SELECT 1": return "1"
        if "ct_schema" in query:
            return "wrong" if self.failure == "schema" else self.databases[database]
        raise AssertionError(query)

    def health(self, database=None):
        self.calls.append("health")
        if database and self.failure == "health":
            raise RunnerError("APPLICATION_HEALTH_FAILED")
        if database:
            assert database in self.jdbc.read_text()


class LocalBridge:
    def __init__(self, host): self.host = host
    def configuration_error(self): return None
    def call(self, action, run_id=None):
        return self.host.check() if action == "check" else self.host.run(run_id)


class VersionSwitchTests(EnvironmentTestCase):
    def setUp(self):
        super().setUp()
        self.settings = self.settings.model_copy(update={"operation_mode": "switch_version"})
        self.server = self.settings.path("server")
        (self.server / "conf").mkdir(parents=True)
        (self.server / "bin").mkdir()
        (self.server / "webapps/app").mkdir(parents=True)
        (self.server / "webapps/app/old.txt").write_text("old exploded")
        (self.server / "conf/server.xml").write_text("<Server/>")
        self.jdbc = self.server / "conf/context.xml"
        self.original_jdbc = '<Context><!--keep--><Resource name="jdbc/ConTrack" url="jdbc:postgresql://127.0.0.1:5439/existing_db?ssl=false&amp;ApplicationName=ct" password="SECRET"/><Resource name="jdbc/Other" url="jdbc:postgresql://other/keep"/></Context>'
        self.jdbc.write_text(self.original_jdbc)
        (self.server / "webapps/app.war").write_bytes(b"old WAR")
        (self.server / "webapps/other.war").write_bytes(b"other WAR")
        source = self.root / "catalog/wars/5.2.0/release"
        manifest = read_yaml(source / "manifest.yaml")
        manifest["artifact"]["file"] = "app.war"
        write_yaml(source / "manifest.yaml", manifest)
        (source / "app.war").write_bytes(b"new app WAR")
        self.config = {"root": str(self.root), "postgres": {"container": "pg-demo", "user": "contrack"},
                       "jdbc": {"file": "runtime/server/conf/context.xml", "format": "xml_resource", "resource_name": "jdbc/ConTrack"},
                       "schema_version_query": "SELECT schema_version FROM app_version",
                       "start_command": ["start-demo"], "stop_command": ["stop-demo"],
                       "health_url": "http://127.0.0.1:8080/app/", "stop_timeout": 0}
        self.host = SimulatedHost(self.config)
        self.service = VersionSwitchService(self.settings, LocalBridge(self.host))
        self.payload = SwitchVersionRequest(war_id="WAR-520-release", database_profile_id="DB-520")

    def switch(self):
        state, lock = self.service.begin(self.payload, "demo-user")
        self.service.execute(state, lock)
        return self.service.history.get(state["run_id"])

    def test_switch_restores_fresh_db_then_stops_changes_jdbc_and_app_war_and_checks_health(self):
        run = self.switch()
        self.assertEqual(run["status"], "READY", run["log"])
        self.assertIn(run["working_database"], self.jdbc.read_text())
        self.assertEqual((self.server / "webapps/app.war").read_bytes(), b"new app WAR")
        self.assertEqual((self.server / "webapps/other.war").read_bytes(), b"other WAR")
        self.assertIn('password="SECRET"', self.jdbc.read_text())
        self.assertIn('url="jdbc:postgresql://other/keep"', self.jdbc.read_text())
        self.assertIn("<!--keep-->", self.jdbc.read_text())
        self.assertEqual(self.host.calls[:5], ["createdb", "pg_restore", "stop", "start", "health"])
        self.assertEqual(self.host.databases["existing_db"], "5.2.0")
        self.assertTrue((self.service.history.directory(run["run_id"]) / "backup/exploded/old.txt").is_file())
        self.assertEqual(self.service.runtime.get_current_environment()["database"], run["working_database"])
        self.assertFalse(EnvironmentLock.busy(self.settings.path("lock")))
        self.assertNotIn("SECRET", run["log"])
        self.assertNotIn("SECRET", json.dumps(run["recipe"]))

    def test_switch_again_creates_another_database_and_preserves_previous_one(self):
        first = self.switch()
        second = self.switch()
        self.assertNotEqual(first["working_database"], second["working_database"])
        self.assertIn(first["working_database"], self.host.databases)
        self.assertEqual(second["status"], "READY")

    def test_restore_or_schema_failure_does_not_stop_tomcat_or_change_current_files(self):
        for failure in ("pg_restore", "schema"):
            with self.subTest(failure=failure):
                self.host.failure = failure
                self.host.calls.clear()
                run = self.switch()
                self.assertEqual(run["status"], "FAILED")
                self.assertNotIn("stop", self.host.calls)
                self.assertEqual(self.jdbc.read_text(), self.original_jdbc)
                self.assertEqual((self.server / "webapps/app.war").read_bytes(), b"old WAR")
                self.assertTrue((self.server / "webapps/app/old.txt").is_file())

    def test_failed_candidate_start_or_health_restores_previous_war_jdbc_and_exploded_app(self):
        for failure in ("start", "health"):
            with self.subTest(failure=failure):
                self.host.failure = failure
                run = self.switch()
                self.assertEqual(run["status"], "FAILED")
                self.assertEqual(run["rollback_status"], "SUCCESS")
                self.assertTrue(self.host.active)
                self.assertEqual(self.jdbc.read_text(), self.original_jdbc)
                self.assertEqual((self.server / "webapps/app.war").read_bytes(), b"old WAR")
                self.assertTrue((self.server / "webapps/app/old.txt").is_file())
                self.assertIn(run["working_database"], self.host.databases)

    def test_schema_mismatch_is_rejected_before_queue_or_external_commands(self):
        with self.assertRaises(EnvironmentError) as caught:
            self.service.begin(SwitchVersionRequest(war_id="WAR-520-release", database_profile_id="DB-510"), "demo")
        self.assertEqual(caught.exception.code, "SCHEMA_MISMATCH")
        self.assertEqual(self.host.calls, [])

    def test_catalog_ignores_bundle_repository_and_loads_nested_database_manifests(self):
        (self.root / "catalog/bundles/520-release.yaml").write_text("bad: bundle")
        (self.root / "catalog/repositories/svn/standard-v1/manifest.yaml").write_text("bad: repository")
        catalog = self.service.catalog()
        self.assertEqual(len(catalog["databases"]), 2)
        self.assertEqual(self.switch()["status"], "READY")

    def test_war_filename_mismatch_is_rejected_before_db_creation(self):
        payload = SwitchVersionRequest(war_id="WAR-520-hf8383", database_profile_id="DB-520")
        with self.assertRaises(EnvironmentError) as caught:
            self.service.begin(payload, "demo")
        self.assertEqual(caught.exception.code, "WAR_FILENAME_MISMATCH")
        self.assertEqual(self.host.calls, [])

    def test_catalog_mutation_after_queue_fails_before_creating_database(self):
        state, lock = self.service.begin(self.payload, "demo")
        (self.root / "catalog/wars/5.2.0/release/app.war").write_bytes(b"changed")
        self.service.execute(state, lock)
        run = self.service.history.get(state["run_id"])
        self.assertEqual(run["error"]["code"], "ARTIFACT_MISMATCH")
        self.assertNotIn("createdb", self.host.calls)

    def test_host_lock_blocks_all_environment_operations_even_if_backend_has_exited(self):
        main = self.settings.path("lock")
        with file_lock(main.with_name(main.name + ".host")):
            self.assertTrue(EnvironmentLock.busy(main))
            with self.assertRaises(EnvironmentError) as caught:
                self.service.begin(self.payload, "demo")
            self.assertEqual(caught.exception.code, "ENVIRONMENT_BUSY")

    def test_ssh_disconnect_keeps_host_progress_and_host_lock_authoritative(self):
        state, lock = self.service.begin(self.payload, "demo")
        main = self.settings.path("lock")
        with file_lock(main.with_name(main.name + ".host")), \
             patch.object(self.service.runner, "call", side_effect=EnvironmentError("Disconnected")), \
             self.assertLogs("app.modules.contrack_environments.version_switch", level="ERROR"):
            self.service.execute(state, lock)
            self.assertTrue(EnvironmentLock.busy(main))
            self.assertEqual(read_yaml(self.service.history.directory(state["run_id"]) / "state.yaml")["status"], "QUEUED")

    def test_restricted_ssh_command_rejects_shell_and_arbitrary_operations(self):
        from app.modules.contrack_environments.host_runner import main
        for command in ("bash", "run 20261123T100000-aaaaaaaaaaaa; touch /tmp/bad", "check extra", ""):
            with self.subTest(command=command), patch("sys.argv", ["runner", "--config", "unused", "serve"]), \
                 patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": command}):
                output = io.StringIO()
                with redirect_stdout(output):
                    result = main()
                self.assertEqual(result, 1)
                self.assertEqual(json.loads(output.getvalue())["code"], "INVALID_HOST_OPERATION")

    def test_runner_refuses_delayed_request_without_orchestrator_and_replayed_request(self):
        state, lock = self.service.begin(self.payload, "demo")
        lock.release()
        with self.assertRaises(RunnerError) as caught:
            self.host.run(state["run_id"])
        self.assertEqual(caught.exception.code, "ORCHESTRATOR_NOT_LOCKED")
        lock.acquire()
        try:
            self.host.run(state["run_id"])
            with self.assertRaises(FileExistsError):
                self.host.run(state["run_id"])
        finally:
            lock.release()

    def test_preflight_and_transport_errors_do_not_echo_credentials(self):
        runner = SSHHostRunner(self.settings)
        self.assertIn("ssh_host", runner.configuration_error())
        settings = self.settings.model_copy(deep=True)
        settings.switch_version.ssh_host = "127.0.0.1"
        settings.switch_version.ssh_user = "demo"
        runner = SSHHostRunner(settings)
        with patch.object(runner, "configuration_error", return_value=None), patch("subprocess.run", return_value=SimpleNamespace(returncode=255, stdout="", stderr="SECRET")):
            with self.assertRaises(EnvironmentError) as caught:
                runner.call("check")
        self.assertNotIn("SECRET", str(caught.exception))

    def test_switch_disabled_in_other_modes_and_uncertain_previous_state_blocks_switch(self):
        settings = self.settings.model_copy(update={"operation_mode": "deploy_war"})
        with self.assertRaises(EnvironmentError):
            VersionSwitchService(settings, LocalBridge(self.host)).validate(self.payload)
        self.service.runtime.save({"status": "UNKNOWN"})
        with self.assertRaises(EnvironmentError) as caught:
            self.service.begin(self.payload, "demo")
        self.assertEqual(caught.exception.code, "PREVIOUS_SWITCH_UNCERTAIN")

    def test_jdbc_file_under_catalog_or_exploded_application_is_rejected(self):
        for relative in ("catalog/databases/5.2.0/standard-v1/baseline.dump", "runtime/server/webapps/app/old.txt"):
            with self.subTest(relative=relative), self.assertRaises(RunnerError):
                HostRunner({**self.config, "jdbc": {**self.config["jdbc"], "file": relative}})

    def test_failure_moving_old_exploded_directory_keeps_original_directory_on_rollback(self):
        original = Path.rename
        def rename(path, target):
            if path == self.host.exploded:
                raise OSError("Cannot move existing exploded directory")
            return original(path, target)
        with patch.object(Path, "rename", rename):
            run = self.switch()
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["rollback_status"], "SUCCESS")
        self.assertTrue((self.server / "webapps/app/old.txt").is_file())
        self.assertEqual(self.jdbc.read_text(), self.original_jdbc)

    def test_failed_stop_does_not_replace_war_or_jdbc_or_claim_rollback_success(self):
        self.host.failure = "stop"
        run = self.switch()
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["rollback_status"], "FAILED")
        self.assertEqual((self.server / "webapps/app.war").read_bytes(), b"old WAR")
        self.assertEqual(self.jdbc.read_text(), self.original_jdbc)
        self.assertEqual(self.service.runtime.get_current_environment()["status"], "UNKNOWN")

    def test_http_success_without_target_database_connections_cannot_pass_health(self):
        self.host.config["health_timeout"] = 0
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(self.host, "sql", return_value="0"), \
             patch("app.modules.contrack_environments.host_runner.urlopen", return_value=response):
            with self.assertRaises(RunnerError) as caught:
                HostRunner.health(self.host, "ct_new")
        self.assertEqual(caught.exception.code, "APPLICATION_HEALTH_FAILED")

    def test_switch_api_round_trip_permission_and_rejects_browser_supplied_commands(self):
        from app.modules.contrack_environments.router import get_service, router
        from app.modules.contrack_environments.service import EnvironmentPreparationService
        app = FastAPI()
        app.include_router(router, prefix="/api")
        service = EnvironmentPreparationService(self.settings)
        app.dependency_overrides[get_service] = lambda: service
        for route in router.routes:
            for dependency in route.dependant.dependencies:
                if dependency.call is not get_service:
                    app.dependency_overrides[dependency.call] = lambda: SimpleNamespace(username="api-user")
        client = TestClient(app)
        payload = self.payload.model_dump()
        base = "/api/contrack-environments"
        with patch("app.modules.contrack_environments.router.VersionSwitchService", return_value=self.service):
            self.assertEqual(client.get(base + "/catalog").json()["operation_mode"], "switch_version")
            self.assertEqual(client.post(base + "/switch/validate", json=payload).status_code, 200)
            self.assertEqual(self.host.calls, [])
            self.assertEqual(client.post(base + "/switch", json={**payload, "command": "evil"}).status_code, 422)
            response = client.post(base + "/switch", json=payload)
            self.assertEqual(response.status_code, 202)
            run = client.get(base + "/runs/" + response.json()["run_id"]).json()
            self.assertEqual(run["status"], "READY")
            app.dependency_overrides = {get_service: lambda: service}
            self.assertEqual(client.post(base + "/switch", json=payload).status_code, 401)


class HostConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "host-switch.json"

    def test_missing_config_cli_reports_actionable_error_without_invoking_host_commands(self):
        from app.modules.contrack_environments.host_runner import main
        output = io.StringIO()
        with patch("sys.argv", ["runner", "--config", str(self.path), "check"]), \
             patch("app.modules.contrack_environments.host_runner.HostRunner") as runner, redirect_stdout(output):
            self.assertEqual(main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {"ok": False, "code": "HOST_CONFIG_NOT_FOUND"})
        runner.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_json_syntax_errors_report_location_without_config_values(self):
        self.path.write_text('{\n  "password": "SECRET_VALUE",\n}', encoding="utf-8")
        with self.assertRaises(RunnerError) as caught:
            load_host_config(self.path)
        self.assertEqual(caught.exception.code, "HOST_CONFIG_INVALID_JSON")
        self.assertEqual(caught.exception.line, 3)
        self.assertEqual(caught.exception.column, 1)
        self.assertNotIn("SECRET_VALUE", str(caught.exception))

    def test_permission_and_encoding_errors_have_specific_codes_without_exception_text(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("SECRET_VALUE")):
            with self.assertRaises(RunnerError) as caught:
                load_host_config(self.path)
        self.assertEqual(caught.exception.code, "HOST_CONFIG_PERMISSION_DENIED")
        self.assertNotIn("SECRET_VALUE", str(caught.exception))
        self.path.write_bytes(b"\xff\xfe invalid")
        with self.assertRaises(RunnerError) as caught:
            load_host_config(self.path)
        self.assertEqual(caught.exception.code, "HOST_CONFIG_INVALID_UTF8")

    def test_non_object_is_rejected_and_utf8_bom_object_is_accepted(self):
        self.path.write_text('["SECRET_VALUE"]', encoding="utf-8")
        with self.assertRaises(RunnerError) as caught:
            load_host_config(self.path)
        self.assertEqual(caught.exception.code, "HOST_CONFIG_NOT_OBJECT")
        self.path.write_text('{"root":"/demo"}', encoding="utf-8-sig")
        self.assertEqual(load_host_config(self.path), {"root": "/demo"})


class JDBCEditTests(EnvironmentTestCase):
    def test_properties_retains_other_keys_comments_crlf_and_connection_options(self):
        text = "# keep\r\njdbc.url = jdbc:postgresql://localhost:5439/old?ssl=false\r\njdbc.password=SECRET\r\n"
        result = change_jdbc(text, {"format": "properties", "property": "jdbc.url"}, "ct_new")
        self.assertEqual(result, text.replace("/old?", "/ct_new?"))

    def test_duplicate_or_missing_selectors_and_nonstandard_jdbc_urls_are_rejected(self):
        for text in ("jdbc.url=x\njdbc.url=y", "other=x", "jdbc.url=jdbc:postgresql:old"):
            with self.subTest(text=text), self.assertRaises(RunnerError):
                change_jdbc(text, {"format": "properties", "property": "jdbc.url"}, "ct_new")

    def test_escaped_java_properties_url(self):
        result = change_jdbc(r"jdbc.url=jdbc\:postgresql\://localhost\:5439/old", {"format": "properties", "property": "jdbc.url"}, "ct_new")
        self.assertEqual(result, r"jdbc.url=jdbc\:postgresql\://localhost\:5439/ct_new")
