from __future__ import annotations

import copy
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.modules.contrack_environments.adapters import LinuxEnvironmentAdapter
from app.modules.contrack_environments.catalog import PrepareRequest, VersionCatalogService, repository_address
from app.modules.contrack_environments.config import EnvironmentError, EnvironmentSettings, contained
from app.modules.contrack_environments.service import EnvironmentPreparationService
from app.modules.contrack_environments.state import EnvironmentLock, read_yaml, working_database_name, write_yaml


def fixture_catalog(root):
    for version in ("5.1.0", "5.2.0"):
        short = version.replace(".", "")
        database = {"database_id": f"DB-{short}", "schema_version": version, "profile_type": "standard",
                    "artifact": {"file": "baseline.dump"}, "status": "available"}
        folder = root / "catalog/databases" / version / "standard-v1"
        write_yaml(folder / "manifest.yaml", database)
        (folder / "baseline.dump").write_bytes(version.encode())
        for build in (["release", "hf8383"] if version == "5.2.0" else ["release"]):
            war_id = f"WAR-{short}-{build}"
            war = {"war_id": war_id, "display_version": version, "build_type": build, "build_id": "001",
                   "artifact": {"file": "contrack.war"}, "compatibility": {"database_schema": version}, "status": "available"}
            folder = root / "catalog/wars" / version / build
            write_yaml(folder / "manifest.yaml", war)
            (folder / "contrack.war").write_bytes(f"war-{version}-{build}".encode())
            bundle = {"bundle_id": f"CT-{short}-{build}", "display_name": f"ConTrack {version} {build}",
                      "application": {"war_id": war_id},
                      "database": {"schema_version": version, "default_database_id": f"DB-{short}"},
                      "repository": {"default_repository_id": "SVN-STANDARD"}, "status": "available"}
            write_yaml(root / f"catalog/bundles/{short}-{build}.yaml", bundle)
    write_yaml(root / "catalog/repositories/svn/standard-v1/manifest.yaml", {
        "repository_id": "SVN-STANDARD", "repository_type": "svn", "url": "svn://svn.internal/project", "status": "available",
    })


class FakeAdapter:
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = []
        self.databases = {}

    def record(self, name, *args):
        self.calls.append((name, *args))
        if name == self.failure:
            raise EnvironmentError(f"Simulated {name} failure", name.upper() + "_FAILED")

    def preflight(self, recipe): self.record("preflight")
    def stage(self, recipe, database, directory): self.record("stage", database)
    def create_database(self, database):
        self.record("create_database", database)
        if database in self.databases:
            raise AssertionError("Working databases must never be reused")
        self.databases[database] = None
    def restore_database(self, database, source):
        self.record("restore_database", database)
        self.databases[database] = source.read_text()
    def check_schema(self, database, expected):
        self.record("check_schema", database, expected)
        if self.databases[database] != expected:
            raise EnvironmentError("Schema mismatch", "SCHEMA_MISMATCH")
    def prepare_repository(self, recipe, directory): self.record("prepare_repository", recipe.repository.repository_id)
    def stop(self): self.record("stop")
    def deploy(self, recipe, directory): self.record("deploy", recipe.war.war_id)
    def start(self): self.record("start")
    def health(self, recipe, database):
        self.record("health", database)
        return dict.fromkeys(("process", "port", "war", "database", "schema", "application"), True)


class EnvironmentTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.settings = EnvironmentSettings(root=self.root, enabled=True)
        fixture_catalog(self.root)

    def service(self, failure=None):
        return EnvironmentPreparationService(self.settings, FakeAdapter(failure))

    def run_bundle(self, service, bundle="CT-520-release"):
        state, recipe, lock = service.begin(PrepareRequest(bundle_id=bundle), "test-user")
        service.execute(state, recipe, lock)
        return service.history.get(state["run_id"])

    def assert_error(self, code, operation):
        with self.assertRaises(EnvironmentError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)


class CatalogTests(EnvironmentTestCase):
    def test_load_valid_war_database_bundle_and_recipe(self):
        catalog = VersionCatalogService(self.settings)
        self.assertEqual(len(catalog.wars), 3)
        self.assertEqual(len(catalog.databases), 2)
        self.assertEqual(len(catalog.bundles), 3)
        recipe = catalog.resolve(PrepareRequest(bundle_id="CT-520-release"))
        self.assertEqual(recipe.public()["schema_version"], "5.2.0")
        self.assertEqual(recipe.public()["database_baseline"], "DB-520")
        self.assertTrue(all(v["status"] == "available" for v in catalog.list_available_contrack_versions()["versions"]))

    def test_missing_war(self):
        (self.root / "catalog/wars/5.2.0/release/contrack.war").unlink()
        catalog = VersionCatalogService(self.settings)
        self.assert_error("ARTIFACT_NOT_FOUND", lambda: catalog.resolve(PrepareRequest(bundle_id="CT-520-release")))

    def test_missing_database(self):
        (self.root / "catalog/databases/5.2.0/standard-v1/manifest.yaml").unlink()
        self.assert_error("ARTIFACT_NOT_FOUND", lambda: VersionCatalogService(self.settings).resolve(PrepareRequest(bundle_id="CT-520-release")))

    def test_invalid_bundle(self):
        path = self.root / "catalog/bundles/520-release.yaml"
        value = read_yaml(path)
        value["execute"] = "untrusted-command"
        write_yaml(path, value)
        self.assert_error("INVALID_MANIFEST", lambda: VersionCatalogService(self.settings))

    def test_schema_mismatch_and_unavailable_artifact(self):
        catalog = VersionCatalogService(self.settings)
        self.assert_error("SCHEMA_MISMATCH", lambda: catalog.resolve(PrepareRequest(bundle_id="CT-520-release", database_profile_id="DB-510")))
        war = catalog.wars["WAR-520-release"]
        catalog.wars[war.war_id] = war.model_copy(update={"status": "archived"})
        self.assert_error("ARTIFACT_UNAVAILABLE", lambda: catalog.resolve(PrepareRequest(bundle_id="CT-520-release")))

    def test_war_schema_must_match_not_only_bundle(self):
        path = self.root / "catalog/wars/5.2.0/release/manifest.yaml"
        value = read_yaml(path)
        value["compatibility"]["database_schema"] = "5.1.0"
        write_yaml(path, value)
        self.assert_error("SCHEMA_MISMATCH", lambda: VersionCatalogService(self.settings).resolve(PrepareRequest(bundle_id="CT-520-release")))

    def test_duplicate_ids_rejected(self):
        source = self.root / "catalog/bundles/520-release.yaml"
        (source.parent / "duplicate.yaml").write_bytes(source.read_bytes())
        self.assert_error("INVALID_MANIFEST", lambda: VersionCatalogService(self.settings))

    def test_ids_and_artifact_paths_cannot_escape(self):
        catalog = VersionCatalogService(self.settings)
        for invalid in ("../outside", "a/../../b", "C:\\secret", "..", "-x", "foo\nbar"):
            self.assert_error("INVALID_ID", lambda: catalog.resolve(PrepareRequest(bundle_id=invalid)))
        path = self.root / "catalog/wars/5.2.0/release/manifest.yaml"
        value = read_yaml(path)
        value["artifact"]["file"] = "../../../../outside.war"
        write_yaml(path, value)
        self.assert_error("INVALID_MANIFEST", lambda: VersionCatalogService(self.settings))

    def test_checksum_mismatch(self):
        path = self.root / "catalog/wars/5.2.0/release/manifest.yaml"
        value = read_yaml(path)
        value["artifact"]["sha256"] = "0" * 64
        write_yaml(path, value)
        self.assert_error("CHECKSUM_MISMATCH", lambda: VersionCatalogService(self.settings).resolve(PrepareRequest(bundle_id="CT-520-release")))

    def test_repository_credentials_and_invalid_url_rejected(self):
        repo = VersionCatalogService(self.settings).repositories["SVN-STANDARD"]
        self.assertEqual(repository_address(repo), ("svn.internal", 3690))
        for url in ("file:///etc/passwd", "https://user:secret@example.org/repo", "svn://"):
            self.assert_error("REPOSITORY_CONFIG", lambda: repository_address(repo.model_copy(update={"url": url})))

    def test_overlapping_or_escaping_configuration_paths_rejected(self):
        for values in ({"server": "catalog/wars/runtime"}, {"runs": "../elsewhere"}, {"lock": "runtime/server/lock"}):
            with self.assertRaises((ValidationError, EnvironmentError)):
                EnvironmentSettings(root=self.root, **values)


class PreparationTests(EnvironmentTestCase):
    def test_atomic_state_write_retries_transient_windows_replace_denial(self):
        path = self.root / "state.yaml"
        write_yaml(path, {"status": "before"})
        original = os.replace
        calls = []

        def replace(source, target):
            calls.append(target)
            if len(calls) == 1:
                error = PermissionError("Simulated transient Windows file sharing denial")
                error.winerror = 5
                raise error
            return original(source, target)

        with patch("app.modules.contrack_environments.state.os.replace", side_effect=replace), \
                patch("app.modules.contrack_environments.state.time.sleep"):
            write_yaml(path, {"status": "after"})
        self.assertEqual(read_yaml(path)["status"], "after")
        self.assertEqual(len(calls), 2)

    def test_atomic_state_write_preserves_old_state_on_permanent_failure(self):
        path = self.root / "state.yaml"
        write_yaml(path, {"status": "before"})
        with patch("app.modules.contrack_environments.state.os.replace", side_effect=PermissionError("Permanent permission error")):
            with self.assertRaises(PermissionError):
                write_yaml(path, {"status": "after"})
        self.assertEqual(read_yaml(path)["status"], "before")
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_success_creates_history_runtime_state_and_unique_working_database(self):
        service = self.service()
        run = self.run_bundle(service)
        self.assertEqual(run["status"], "READY")
        self.assertTrue(all(status == "SUCCESS" for status in run["steps"].values()))
        self.assertEqual(service.runtime.get_current_environment()["run_id"], run["run_id"])
        for name in ("request.yaml", "recipe.yaml", "state.yaml", "run.log"):
            self.assertTrue((service.history.directory(run["run_id"]) / name).is_file())
        self.assertTrue((self.settings.path("runtime_databases") / "current.yaml").is_file())
        self.assertEqual(self.run_bundle(service)["status"], "READY")
        self.assertEqual(len(service.adapter.databases), 2)

    def test_working_database_name_is_safe_bounded_and_unique(self):
        names = [working_database_name("5.2.0/unsafe" * 12, f"run-{i:012x}") for i in range(10)]
        self.assertEqual(len(set(names)), 10)
        self.assertTrue(all(re.fullmatch(r"[a-z][a-z0-9_]{1,62}", name) for name in names))

    def test_failed_restore_stops_before_touching_current_server(self):
        service = self.service()
        self.run_bundle(service, "CT-510-release")
        previous = copy.deepcopy(service.runtime.get_current_environment())
        service.adapter.calls.clear()
        service.adapter.failure = "restore_database"
        run = self.run_bundle(service)
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["failed_step"], "database_restore")
        self.assertFalse(any(call[0] in ("stop", "deploy", "start") for call in service.adapter.calls))
        self.assertEqual(service.runtime.get_current_environment(), previous)
        self.assertIn("FAILED", run["log"])

    def test_failed_server_start_keeps_run_failed_and_releases_lock(self):
        service = self.service("start")
        run = self.run_bundle(service)
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["failed_step"], "server_start")
        self.assertFalse(any(call[0] == "health" for call in service.adapter.calls))
        self.assertNotEqual(service.runtime.get_current_environment()["status"], "RUNNING")
        self.assertFalse(EnvironmentLock.busy(self.settings.path("lock")))

    def test_failed_health_check_stops_candidate_without_publishing_ready(self):
        service = self.service("health")
        run = self.run_bundle(service)
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["failed_step"], "health_check")
        self.assertEqual([call[0] for call in service.adapter.calls].count("stop"), 2)
        self.assertEqual(service.runtime.get_current_environment()["status"], "FAILED")

    def test_two_users_cannot_prepare_concurrently(self):
        service = self.service()
        state, recipe, lock = service.begin(PrepareRequest(bundle_id="CT-520-release"), "user-a")
        try:
            self.assert_error("ENVIRONMENT_BUSY", lambda: self.service().begin(PrepareRequest(bundle_id="CT-510-release"), "user-b"))
            env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
            code = "from pathlib import Path; from app.modules.contrack_environments.state import EnvironmentLock; import sys; sys.exit(0 if EnvironmentLock.busy(Path(sys.argv[1])) else 1)"
            result = subprocess.run([sys.executable, "-c", code, str(self.settings.path("lock"))], env=env, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
        finally:
            lock.release()

    def test_interrupted_run_is_reported_and_preserved(self):
        service = self.service()
        state, _, lock = service.begin(PrepareRequest(bundle_id="CT-520-release"), "test-user")
        lock.release()  # Simulate a process exiting before its background task runs.
        self.assertEqual(service.history.get(state["run_id"])["status"], "INTERRUPTED")
        self.run_bundle(service)
        self.assertEqual(read_yaml(service.history.directory(state["run_id"]) / "state.yaml")["status"], "INTERRUPTED")

    def test_crash_before_committing_ready_cannot_publish_running(self):
        service = self.service()
        run = self.run_bundle(service)
        state = read_yaml(service.history.directory(run["run_id"]) / "state.yaml")
        state["status"] = "PREPARING"
        service.history.save(state)
        self.assertEqual(service.runtime.get_current_environment()["status"], "UNKNOWN")

    def test_catalog_mutation_after_acceptance_rejected_before_database_create(self):
        service = self.service()
        state, recipe, lock = service.begin(PrepareRequest(bundle_id="CT-520-release"), "test-user")
        recipe.baseline_path.write_bytes(b"changed")
        service.execute(state, recipe, lock)
        run = service.history.get(state["run_id"])
        self.assertEqual(run["failed_step"], "validate")
        self.assertNotIn("create_database", [call[0] for call in service.adapter.calls])

    def test_upgrade_hotfix_and_older_version_use_separate_databases(self):
        service = self.service()
        baselines = {p: p.read_bytes() for p in (self.root / "catalog").rglob("baseline.dump")}
        records = [self.run_bundle(service, bundle) for bundle in
                   ("CT-510-release", "CT-520-release", "CT-520-hf8383", "CT-510-release")]
        self.assertTrue(all(record["status"] == "READY" for record in records))
        self.assertEqual(len(set(record["working_database"] for record in records)), 4)
        self.assertEqual([service.adapter.databases[record["working_database"]] for record in records],
                         ["5.1.0", "5.2.0", "5.2.0", "5.1.0"])
        self.assertTrue(all(path.read_bytes() == before for path, before in baselines.items()))
        self.assertEqual(service.runtime.get_current_environment()["bundle"], "CT-510-release")

    def test_failed_schema_validation_never_stops_current_application(self):
        service = self.service("check_schema")
        run = self.run_bundle(service)
        self.assertEqual(run["failed_step"], "database_schema")
        self.assertNotIn("stop", [call[0] for call in service.adapter.calls])

    def test_history_pagination_and_run_path_validation(self):
        service = self.service()
        self.run_bundle(service)
        self.run_bundle(service)
        history = service.history.list(limit=1, offset=1)
        self.assertEqual(history["total"], 2)
        self.assertEqual(len(history["items"]), 1)
        self.assert_error("INVALID_RUN_ID", lambda: service.history.get("../../secrets"))

    def test_disabled_feature_rejects_before_creating_directories(self):
        service = EnvironmentPreparationService(self.settings.model_copy(update={"enabled": False}), FakeAdapter())
        self.assert_error("FEATURE_DISABLED", lambda: service.begin(PrepareRequest(bundle_id="CT-520-release"), "test"))
        self.assertFalse(self.settings.path("lock").exists())


class AdapterTests(EnvironmentTestCase):
    def templates(self):
        root = self.root / "templates"
        root.mkdir()
        (root / "server.xml").write_text('<Server><Service><Connector port="{{SERVER_PORT}}" /></Service></Server>')
        (root / "application.properties").write_text("database={{DATABASE_NAME}}\njdbc={{JDBC_URL}}\nrepository={{REPOSITORY_URL}}\n")
        settings = self.settings.model_copy(update={"config_templates": str(root)})
        return LinuxEnvironmentAdapter(settings), root

    def test_stage_and_deploy_war_config_without_mutating_catalog_or_other_webapps(self):
        adapter, templates = self.templates()
        recipe = VersionCatalogService(self.settings).resolve(PrepareRequest(bundle_id="CT-520-release"))
        stage = self.root / "stage"
        stage.mkdir()
        original = recipe.war_path.read_bytes()
        adapter.stage(recipe, "ct_520_new", stage)
        rendered = (stage / "staged-conf/application.properties").read_text()
        self.assertIn("ct_520_new", rendered)
        self.assertIn("svn://svn.internal/project", rendered)
        self.assertNotIn("{{", rendered)
        self.assertIn("{{DATABASE_NAME}}", (templates / "application.properties").read_text())
        webapps = self.settings.path("server") / "webapps"
        (webapps / "contrack").mkdir(parents=True)
        (webapps / "contrack/stale.class").write_bytes(b"old")
        (webapps / "other.war").write_bytes(b"preserve")
        adapter.deploy(recipe, stage)
        self.assertEqual((webapps / "contrack.war").read_bytes(), original)
        self.assertFalse((webapps / "contrack").exists())
        self.assertEqual((webapps / "other.war").read_bytes(), b"preserve")
        self.assertEqual(recipe.war_path.read_bytes(), original)

    def test_bad_template_fails_before_deployment(self):
        adapter, templates = self.templates()
        (templates / "server.xml").write_text('<Server><Connector port="9999" /></Server>')
        recipe = VersionCatalogService(self.settings).resolve(PrepareRequest(bundle_id="CT-520-release"))
        stage = self.root / "stage"
        stage.mkdir()
        self.assert_error("TEMPLATE_CONFIG", lambda: adapter.stage(recipe, "ct_520_test", stage))
        self.assertFalse(self.settings.path("server").exists())

    def test_health_requires_all_six_checks(self):
        adapter = LinuxEnvironmentAdapter(self.settings)
        recipe = VersionCatalogService(self.settings).resolve(PrepareRequest(bundle_id="CT-520-release"))
        target = self.settings.path("server") / "webapps/contrack.war"
        target.parent.mkdir(parents=True)
        target.write_bytes(recipe.war_path.read_bytes())
        response = SimpleNamespace(status=200, geturl=lambda: self.settings.health_url)
        from contextlib import nullcontext
        with patch.object(adapter, "_managed_pid", return_value=123), patch.object(adapter, "_port_open", return_value=True), \
                patch.object(adapter, "check_schema") as schema, \
                patch("app.modules.contrack_environments.adapters.urlopen", return_value=nullcontext(response)):
            checks = adapter.health(recipe, "ct_520_test")
        self.assertEqual(len(checks), 6)
        self.assertTrue(all(checks.values()))
        schema.assert_called_once_with("ct_520_test", "5.2.0")

    def test_stop_refuses_unmanaged_process(self):
        adapter = LinuxEnvironmentAdapter(self.settings)
        with patch.object(adapter, "_managed_pid", return_value=None), patch.object(adapter, "_port_open", return_value=True), \
                patch.object(adapter, "_command") as command:
            self.assert_error("UNMANAGED_SERVER", adapter.stop)
        command.assert_not_called()

    def test_postgresql_commands_use_argv_and_never_drop_or_downgrade(self):
        adapter = LinuxEnvironmentAdapter(self.settings)
        with patch("app.modules.contrack_environments.adapters.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="5.2.0")) as run:
            adapter.create_database("ct_520_test")
            adapter.restore_database("ct_520_test", self.root / "baseline.dump")
            adapter.check_schema("ct_520_test", "5.2.0")
        self.assertEqual([Path(call.args[0][0]).name for call in run.call_args_list], ["createdb", "pg_restore", "psql"])
        self.assertTrue(all(call.kwargs["shell"] is False for call in run.call_args_list))
        self.assertIn("--single-transaction", run.call_args_list[1].args[0])
        self.assertIn("default_transaction_read_only=on", run.call_args_list[2].kwargs["env"]["PGOPTIONS"])

    def test_external_tool_stderr_is_not_exposed(self):
        adapter = LinuxEnvironmentAdapter(self.settings)
        with patch("app.modules.contrack_environments.adapters.subprocess.run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="password=secret-token")):
            with self.assertRaises(EnvironmentError) as caught:
                adapter.create_database("ct_test")
        self.assertNotIn("secret-token", str(caught.exception))

    def test_database_schema_health_rejects_wrong_live_schema(self):
        adapter = LinuxEnvironmentAdapter(self.settings)
        with patch.object(adapter, "_command", return_value="5.1.0"):
            self.assert_error("SCHEMA_MISMATCH", lambda: adapter.check_schema("ct_test", "5.2.0"))


class ApiTests(EnvironmentTestCase):
    def setUp(self):
        super().setUp()
        from app.modules.contrack_environments.router import get_service, router
        self.service_instance = self.service()
        app = FastAPI()
        app.include_router(router, prefix="/api")
        self.app = app
        self.client = TestClient(app)
        app.dependency_overrides[get_service] = lambda: self.service_instance
        # Replace the real permission dependency only in tests; production uses session + DB roles.
        for route in router.routes:
            for dependency in route.dependant.dependencies:
                if dependency.call is not get_service:
                    app.dependency_overrides[dependency.call] = lambda: SimpleNamespace(username="api-test")

    def test_catalog_validate_prepare_and_history_round_trip(self):
        base = "/api/contrack-environments"
        self.assertEqual(self.client.get(base + "/catalog").status_code, 200)
        self.assertEqual(self.client.post(base + "/validate", json={"bundle_id": "CT-520-release"}).status_code, 200)
        response = self.client.post(base + "/prepare", json={"bundle_id": "CT-520-release"})
        self.assertEqual(response.status_code, 202)
        run = self.client.get(base + "/runs/" + response.json()["run_id"]).json()
        self.assertEqual(run["status"], "READY")
        self.assertEqual(self.client.get(base + "/runs").json()["total"], 1)
        self.assertEqual(self.client.get(base + "/current").json()["environment"]["status"], "RUNNING")

    def test_api_rejects_unknown_fields_shell_commands_and_bad_profiles(self):
        base = "/api/contrack-environments"
        self.assertEqual(self.client.post(base + "/prepare", json={"bundle_id": "CT-520-release", "command": "rm"}).status_code, 422)
        self.assertEqual(self.client.post(base + "/prepare", json={"bundle_id": "CT-520-release", "database_profile_id": "DB-510"}).status_code, 400)
        self.assertEqual(self.client.post(base + "/prepare", json={"bundle_id": "../oops"}).status_code, 400)

    def test_routes_require_authentication_and_menu_permission(self):
        from app.modules.contrack_environments.router import get_service
        self.app.dependency_overrides = {get_service: lambda: self.service_instance}
        self.assertEqual(self.client.get("/api/contrack-environments/catalog").status_code, 401)

    def test_disabled_feature_still_renders_status_and_rejects_prepare(self):
        self.service_instance.settings = self.settings.model_copy(update={"enabled": False})
        response = self.client.get("/api/contrack-environments/catalog")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])
        response = self.client.post("/api/contrack-environments/prepare", json={"bundle_id": "CT-520-release"})
        self.assertEqual(response.status_code, 503)

    def test_forbidden_permission_is_enforced(self):
        from app.dependencies import get_current_user
        from app.modules.contrack_environments.router import get_service
        self.app.dependency_overrides = {get_service: lambda: self.service_instance,
                                         get_current_user: lambda: SimpleNamespace(role="qa")}
        with patch("app.dependencies.role_permissions", return_value=[]):
            self.assertEqual(self.client.get("/api/contrack-environments/catalog").status_code, 403)


if __name__ == "__main__":
    unittest.main()
