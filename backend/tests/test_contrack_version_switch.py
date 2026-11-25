import json
import io
import os
import ssl
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_contrack_environments import EnvironmentTestCase
from app.modules.contrack_environments.config import EnvironmentError
from app.modules.contrack_environments.host_runner import HostRunner, RunnerError, change_jdbc, file_lock, health_diagnostic, load_host_config
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
        self.assertTrue(self.service.runtime.get_current_environment()["schema_verified"])
        self.assertFalse(EnvironmentLock.busy(self.settings.path("lock")))
        self.assertNotIn("SECRET", run["log"])
        self.assertNotIn("SECRET", json.dumps(run["recipe"]))

    def test_switch_again_creates_another_database_and_preserves_previous_one(self):
        first = self.switch()
        second = self.switch()
        self.assertNotEqual(first["working_database"], second["working_database"])
        self.assertIn(first["working_database"], self.host.databases)
        self.assertEqual(second["status"], "READY")

    def test_missing_empty_or_null_schema_query_skips_sql_verification_without_claiming_it_passed(self):
        for variant in ("missing", "", None):
            with self.subTest(variant=variant):
                self.config.pop("schema_version_query", None)
                if variant != "missing":
                    self.config["schema_version_query"] = variant
                self.host = SimulatedHost(self.config)
                self.service = VersionSwitchService(self.settings, LocalBridge(self.host))
                preview = self.service.validate(self.payload)
                self.assertEqual(preview["recipe"]["schema_verification"], "manifest_only")
                with patch.object(self.host, "sql", wraps=self.host.sql) as sql:
                    run = self.switch()
                self.assertEqual(run["status"], "READY", run["log"])
                self.assertEqual(run["steps"]["database_schema"], "SKIPPED")
                self.assertFalse(run["schema_verified"])
                self.assertEqual(run["recipe"]["schema_verification"], "manifest_only")
                self.assertFalse(any("ct_schema" in call.args[1] for call in sql.call_args_list))
                current = self.service.runtime.get_current_environment()
                self.assertFalse(current["schema_verified"])
                self.assertFalse(current["health"]["schema_verified"])
                self.assertIn("SKIPPED", run["log"])

    def test_manifest_schema_mismatch_is_still_rejected_when_query_is_disabled(self):
        self.config.pop("schema_version_query")
        host = SimulatedHost(self.config)
        service = VersionSwitchService(self.settings, LocalBridge(host))
        with self.assertRaises(EnvironmentError) as caught:
            service.begin(SwitchVersionRequest(war_id="WAR-520-release", database_profile_id="DB-510"), "demo")
        self.assertEqual(caught.exception.code, "SCHEMA_MISMATCH")
        self.assertEqual(host.calls, [])

    def test_nonempty_invalid_query_remains_an_error_instead_of_silently_disabling_check(self):
        for query in ("REPLACE_WITH_REAL_SELECT_RETURNING_ONE_SCHEMA_VERSION", ";", False):
            with self.subTest(query=query), self.assertRaises(RunnerError):
                SimulatedHost({**self.config, "schema_version_query": query})

    def test_schema_verification_mode_change_after_queue_fails_before_database_creation(self):
        state, lock = self.service.begin(self.payload, "demo")
        self.host.schema_query = ""
        self.service.execute(state, lock)
        run = self.service.history.get(state["run_id"])
        self.assertEqual(run["error"]["code"], "HOST_CONFIGURATION_CHANGED")
        self.assertNotIn("createdb", self.host.calls)

    def parallel_fixture(self):
        war = self.server / "webapps/app##5.2.0.20.war"
        war.write_bytes(b"versioned old WAR")
        directory = self.server / "webapps/app##5.2.0.20"
        directory.mkdir()
        (directory / "old.txt").write_text("versioned old application")
        other = self.server / "webapps/other##1.war"
        other.write_bytes(b"other context")
        return war, directory, other

    def test_parallel_versions_are_previewed_and_archived_only_for_selected_context(self):
        war, directory, other = self.parallel_fixture()
        names = [directory.name, war.name]
        preview = self.service.validate(self.payload)
        self.assertEqual(preview["recipe"]["parallel_deployments"], names)
        self.assertTrue(war.exists())  # Validation is read-only.
        run = self.switch()
        self.assertEqual(run["status"], "READY", run["log"])
        self.assertEqual(run["archived_parallel_deployments"], names)
        self.assertFalse(war.exists())
        self.assertFalse(directory.exists())
        saved = self.service.history.directory(run["run_id"]) / "backup/parallel-webapps"
        self.assertEqual((saved / war.name).read_bytes(), b"versioned old WAR")
        self.assertTrue((saved / directory.name / "old.txt").is_file())
        self.assertEqual(other.read_bytes(), b"other context")
        self.assertEqual((self.server / "webapps/app.war").read_bytes(), b"new app WAR")

    def test_failed_candidate_health_restores_parallel_wars_and_directories(self):
        war, directory, other = self.parallel_fixture()
        self.host.failure = "health"
        run = self.switch()
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["rollback_status"], "SUCCESS")
        self.assertEqual(war.read_bytes(), b"versioned old WAR")
        self.assertTrue((directory / "old.txt").is_file())
        self.assertEqual(other.read_bytes(), b"other context")
        self.assertEqual(self.jdbc.read_text(), self.original_jdbc)

    def test_partial_parallel_archive_failure_restores_already_moved_entries(self):
        war, directory, _ = self.parallel_fixture()
        original = Path.rename
        def rename(path, target):
            if path == war:
                raise OSError("Cannot archive versioned WAR")
            return original(path, target)
        with patch.object(Path, "rename", rename):
            run = self.switch()
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["rollback_status"], "SUCCESS")
        self.assertTrue(war.is_file())
        self.assertTrue((directory / "old.txt").is_file())
        self.assertEqual(self.jdbc.read_text(), self.original_jdbc)

    def test_parallel_deployment_change_after_queue_is_rejected_before_db_creation(self):
        state, lock = self.service.begin(self.payload, "demo")
        self.parallel_fixture()
        self.service.execute(state, lock)
        run = self.service.history.get(state["run_id"])
        self.assertEqual(run["error"]["code"], "PARALLEL_DEPLOYMENTS_CHANGED")
        self.assertNotIn("createdb", self.host.calls)

    def test_parallel_context_descriptors_require_review_before_switch(self):
        folder = self.server / "conf/Catalina/localhost"
        folder.mkdir(parents=True)
        (folder / "app##5.2.0.20.xml").write_text("<Context/>")
        with self.assertRaises(RunnerError) as caught:
            self.host.check()
        self.assertEqual(caught.exception.code, "PARALLEL_CONTEXT_DESCRIPTOR")
        self.assertEqual(self.host.calls, [])

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
        for command in ("bash", "run 20261123T100000-aaaaaaaaaaaa; touch /tmp/bad", "check extra", "recover-stop", "diagnose-health", ""):
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

    def test_invalid_host_configuration_identifies_field_without_echoing_values(self):
        cases = [
            ({"root": str(self.root / "missing")}, "root"),
            ({"jdbc": {**self.config["jdbc"], "file": "runtime/server/conf/SECRET_VALUE.xml"}}, "jdbc.file"),
            ({"jdbc": {**self.config["jdbc"], "format": "invalid"}}, "jdbc.format"),
            ({"jdbc": {**self.config["jdbc"], "resource_name": ""}}, "jdbc.resource_name"),
            ({"command_cwd": "runtime/server/missing"}, "command_cwd"),
            ({"start_command": ["/bin/bash", "./missing-start.sh"]}, "start_command"),
            ({"stop_command": ["/bin/bash", "./missing-stop.sh"]}, "stop_command"),
            ({"postgres": {"container": "bad container", "user": "postgres"}}, "postgres.container"),
            ({"postgres": {"container": "pg16", "user": ""}}, "postgres.user"),
            ({"schema_version_query": "REPLACE_WITH_REAL_SELECT_RETURNING_ONE_SCHEMA_VERSION"}, "schema_version_query"),
            ({"health_url": "https://user:SECRET_VALUE@example.invalid/app"}, "health_url"),
            ({"server_port": 99999}, "server_port"),
        ]
        for update, field in cases:
            with self.subTest(field=field), self.assertRaises(RunnerError) as caught:
                HostRunner({**self.config, **update})
            self.assertEqual(caught.exception.code, "HOST_CONFIGURATION_INVALID")
            self.assertEqual(caught.exception.field, field)
            self.assertNotIn("SECRET_VALUE", str(caught.exception))

    def test_cli_returns_missing_jdbc_field_before_any_database_or_server_command(self):
        from app.modules.contrack_environments.host_runner import main
        path = self.root / "host-switch.json"
        config = {**self.config, "jdbc": {**self.config["jdbc"], "file": "runtime/server/conf/SECRET_VALUE.xml"}}
        path.write_text(json.dumps(config), encoding="utf-8")
        output = io.StringIO()
        with patch("sys.argv", ["runner", "--config", str(path), "check"]), \
             patch("subprocess.run") as process, redirect_stdout(output):
            self.assertEqual(main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {"ok": False, "code": "HOST_CONFIGURATION_INVALID", "field": "jdbc.file"})
        self.assertNotIn("SECRET_VALUE", output.getvalue())
        process.assert_not_called()

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
        self.assertFalse(run["deployment_started"])

    def test_wrong_http_port_is_rejected_before_postgres_or_stop_commands(self):
        (self.server / "conf/server.xml").write_text('<Server port="8005"><Service><Connector port="8282" protocol="org.apache.coyote.http11.Http11NioProtocol"/><Connector port="8009" protocol="AJP/1.3"/></Service></Server>')
        with patch.object(self.host, "sql", wraps=self.host.sql) as sql, self.assertRaises(RunnerError) as caught:
            self.host.check()
        self.assertEqual(caught.exception.code, "HOST_CONFIGURATION_INVALID")
        self.assertEqual(caught.exception.field, "server_port")
        sql.assert_not_called()
        self.assertEqual(self.host.calls, [])
        self.host.server_port = 8282
        self.assertEqual(self.host.check()["http_connector_ports"], [8282])

    def test_http_connector_port_offset_and_dynamic_ports(self):
        xml = self.server / "conf/server.xml"
        xml.write_text('<Server portOffset="100"><Service><Connector port="8182" protocol="HTTP/1.1"/></Service></Server>')
        self.assertEqual(self.host.http_connector_ports(), [8282])
        xml.write_text('<Server><Service><Connector port="${http.port}" protocol="HTTP/1.1"/></Service></Server>')
        self.assertIsNone(self.host.http_connector_ports())
        self.assertTrue(self.host.check()["ok"])

    def test_stop_timeout_reports_a_stopped_process_with_a_busy_foreign_port(self):
        with patch.object(self.host, "port_open", return_value=True), self.assertRaises(RunnerError) as caught:
            self.host.stop()
        self.assertEqual(caught.exception.code, "TOMCAT_STOP_FAILED")
        self.assertEqual(caught.exception.stop_status, {"process_running": False, "port_open": True})
        self.assertEqual(self.host.calls, ["stop"])

    def test_safe_stop_recovery_archives_only_state_and_allows_retry(self):
        self.host.failure = "stop"
        run = self.switch()
        self.host.failure = None
        self.host.active = False
        result = self.host.recover_stop()
        self.assertTrue(result["ok"])
        self.assertEqual(result["run_id"], run["run_id"])
        self.assertIsNone(self.service.runtime.get_current_environment())
        self.assertEqual(read_yaml(self.root / result["state_backup"])["status"], "UNKNOWN")
        self.assertEqual(self.jdbc.read_text(), self.original_jdbc)
        self.assertEqual((self.server / "webapps/app.war").read_bytes(), b"old WAR")
        self.assertEqual(self.service.history.get(run["run_id"])["status"], "FAILED")
        self.assertIn(run["working_database"], self.host.databases)
        self.assertEqual(self.host.recover_stop()["recovery"], "not_required")
        self.assertEqual(self.switch()["status"], "READY")

    def test_stop_recovery_refuses_a_running_tomcat_or_changed_jdbc(self):
        self.host.failure = "stop"
        self.switch()
        with self.assertRaises(RunnerError) as caught:
            self.host.recover_stop()
        self.assertEqual(caught.exception.code, "RECOVERY_TOMCAT_NOT_STOPPED")
        self.host.failure = None
        self.host.active = False
        self.jdbc.write_text(self.original_jdbc + "\n<!--external edit-->")
        with self.assertRaises(RunnerError) as caught:
            self.host.recover_stop()
        self.assertEqual(caught.exception.code, "RECOVERY_JDBC_CHANGED")
        self.assertEqual(self.service.runtime.get_current_environment()["status"], "UNKNOWN")

    def test_stop_recovery_refuses_a_failure_after_war_deploy(self):
        self.host.failure = "health"
        run = self.switch()
        self.host.active = False
        self.service.runtime.save({"status": "UNKNOWN", "attempt_run_id": run["run_id"]})
        with self.assertRaises(RunnerError) as caught:
            self.host.recover_stop()
        self.assertEqual(caught.exception.code, "RECOVERY_NOT_ALLOWED")
        self.assertEqual(self.service.runtime.get_current_environment()["status"], "UNKNOWN")

    def test_stop_recovery_respects_existing_host_lock(self):
        main = self.settings.path("lock")
        with file_lock(main.with_name(main.name + ".host")), self.assertRaises(RunnerError) as caught:
            self.host.recover_stop()
        self.assertEqual(caught.exception.code, "ENVIRONMENT_BUSY")

    def test_http_success_without_target_database_connections_cannot_pass_health(self):
        self.host.config["health_timeout"] = 0
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(self.host, "sql", return_value="0"), \
             patch("app.modules.contrack_environments.host_runner.urlopen", return_value=response):
            with self.assertRaises(RunnerError) as caught:
                HostRunner.health(self.host, "ct_new")
        self.assertEqual(caught.exception.code, "APPLICATION_HEALTH_FAILED")
        self.assertEqual(caught.exception.health_status["database_status"], "no_client_connection")

    def test_custom_health_ca_is_loaded_and_passed_to_https_without_disabling_verification(self):
        ca_file = self.root / "tomcat.crt"
        ca_file.write_text("test certificate loaded by mocked certificate loader")
        context = ssl.create_default_context()
        config = {**self.config, "health_url": "https://localhost:8282/app/", "health_ca_file": str(ca_file)}
        with patch("app.modules.contrack_environments.host_runner.ssl.create_default_context", return_value=context) as loader:
            host = SimulatedHost(config)
        loader.assert_called_once_with(cafile=str(ca_file))
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch("app.modules.contrack_environments.host_runner.urlopen", return_value=response) as request:
            self.assertTrue(host.health_probe()["healthy"])
        request.assert_called_once_with(config["health_url"], timeout=5, context=context)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertIsNone(self.host.health_context)

    def test_invalid_custom_ca_cannot_silently_fall_back_to_unverified_https(self):
        invalid = self.root / "invalid.crt"
        invalid.write_text("SECRET_VALUE is not a certificate")
        for ca_file in (str(self.root / "missing.crt"), str(invalid), "relative.crt", False):
            with self.subTest(ca_file=ca_file), self.assertRaises(RunnerError) as caught:
                SimulatedHost({**self.config, "health_url": "https://localhost/app/", "health_ca_file": ca_file})
            self.assertEqual(caught.exception.field, "health_ca_file")
            self.assertNotIn("SECRET_VALUE", str(caught.exception))

    def test_health_tls_error_is_reported_without_leaking_exception_or_url_credentials(self):
        self.host.config["health_timeout"] = 0
        self.host.health_url = "https://localhost/app/?token=SECRET_VALUE"
        error = URLError(ssl.SSLCertVerificationError(1, "SECRET_VALUE self-signed certificate"))
        with patch("app.modules.contrack_environments.host_runner.urlopen", side_effect=error):
            with self.assertRaises(RunnerError) as caught:
                HostRunner.health(self.host)
        status = caught.exception.health_status
        self.assertEqual(status["http_error"], "TLS_CERTIFICATE_INVALID")
        self.assertTrue(status["process_running"])
        self.assertTrue(status["configured_port_open"])
        self.assertEqual(status["database_status"], "not_requested")
        self.assertNotIn("SECRET_VALUE", json.dumps(status) + health_diagnostic(caught.exception))

    def test_http_error_code_is_retained_without_response_body_or_headers(self):
        error = HTTPError("https://localhost/?token=SECRET_VALUE", 404, "SECRET_VALUE", {}, io.BytesIO(b"SECRET_VALUE"))
        with patch("app.modules.contrack_environments.host_runner.urlopen", side_effect=error):
            status = self.host.health_probe()
        self.assertEqual(status["http_status"], 404)
        self.assertEqual(status["http_error"], "HTTP_ERROR")
        self.assertFalse(status["healthy"])
        self.assertNotIn("SECRET_VALUE", json.dumps(status))

    def test_connection_refusal_is_distinct_from_tls_and_http_errors(self):
        with patch("app.modules.contrack_environments.host_runner.urlopen", side_effect=URLError(ConnectionRefusedError())):
            status = self.host.health_probe()
        self.assertEqual(status["http_error"], "CONNECTION_REFUSED")

    def test_http_200_with_missing_tomcat_process_still_fails_without_querying_database(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(self.host, "running", return_value=False), patch.object(self.host, "sql") as sql, \
                patch("app.modules.contrack_environments.host_runner.urlopen", return_value=response):
            status = self.host.health_probe("ct_new")
        self.assertFalse(status["healthy"])
        self.assertFalse(status["process_running"])
        self.assertEqual(status["database_status"], "waiting_for_readiness")
        sql.assert_not_called()

    def test_target_db_connection_and_all_readiness_conditions_pass_health(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(self.host, "sql", return_value="1") as sql, \
                patch("app.modules.contrack_environments.host_runner.urlopen", return_value=response):
            status = self.host.health_probe("ct_new")
        self.assertTrue(status["healthy"])
        self.assertEqual(status["database_status"], "connected")
        self.assertEqual(sql.call_args.args[0], "ct_new")

    def test_health_retries_transient_tls_errors_and_uses_verified_default_context(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        error = URLError(ssl.SSLCertVerificationError(1, "untrusted certificate"))
        with patch("app.modules.contrack_environments.host_runner.urlopen", side_effect=[error, response]) as request, \
                patch("app.modules.contrack_environments.host_runner.time.sleep") as sleep:
            HostRunner.health(self.host)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.kwargs, {"timeout": 5})
        sleep.assert_called_once_with(2)

    def test_candidate_and_rollback_health_failures_log_diagnostics_and_keep_unknown_state(self):
        status = {"healthy": False, "http_error": "TLS_CERTIFICATE_INVALID", "process_running": True,
                  "configured_port_open": True, "database_status": "not_requested"}
        with patch.object(self.host, "health", side_effect=RunnerError("APPLICATION_HEALTH_FAILED", health_status=status)):
            run = self.switch()
        self.assertEqual(run["failed_step"], "health_check")
        self.assertEqual(run["rollback_status"], "FAILED")
        self.assertEqual(self.service.runtime.get_current_environment()["status"], "UNKNOWN")
        self.assertIn("TLS_CERTIFICATE_INVALID", run["error"]["message"])
        self.assertEqual(run["log"].count("TLS_CERTIFICATE_INVALID"), 2)
        self.assertEqual(self.jdbc.read_text(), self.original_jdbc)
        self.assertTrue((self.server / "webapps/app/old.txt").is_file())

    def test_local_diagnose_health_does_not_switch_files_create_database_or_clear_unknown_state(self):
        from app.modules.contrack_environments.host_runner import main
        self.service.runtime.save({"status": "UNKNOWN", "attempt_run_id": "20261125T100000-aaaaaaaaaaaa"})
        before = (self.settings.path("current") / "version.yaml").read_bytes()
        response = MagicMock()
        response.__enter__.return_value.status = 200
        output = io.StringIO()
        with patch("sys.argv", ["runner", "--config", "unused", "diagnose-health"]), \
                patch("app.modules.contrack_environments.host_runner.load_host_config", return_value=self.config), \
                patch("app.modules.contrack_environments.host_runner.HostRunner", return_value=self.host), \
                patch("app.modules.contrack_environments.host_runner.urlopen", return_value=response), redirect_stdout(output):
            self.assertEqual(main(), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(result["health"]["database_status"], "not_requested")
        self.assertEqual(self.host.calls, [])
        self.assertEqual(self.jdbc.read_text(), self.original_jdbc)
        self.assertEqual((self.settings.path("current") / "version.yaml").read_bytes(), before)

    def test_health_diagnostic_ignores_arbitrary_untrusted_values(self):
        status = {"http_error": "SECRET_VALUE", "database_status": "SECRET_VALUE", "process_running": "SECRET_VALUE",
                  "http_status": "SECRET_VALUE", "url": "SECRET_VALUE", "healthy": False}
        self.assertEqual(json.loads(health_diagnostic(RunnerError("TEST", health_status=status))), {"healthy": False})

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
