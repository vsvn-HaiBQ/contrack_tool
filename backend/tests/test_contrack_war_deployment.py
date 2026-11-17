from pathlib import Path
import os
import errno
import io
import runpy
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from test_contrack_environments import EnvironmentTestCase
from app.modules.contrack_environments.catalog import PrepareRequest, VersionCatalogService
from app.modules.contrack_environments.service import EnvironmentPreparationService
from app.modules.contrack_environments.state import EnvironmentLock, read_yaml, write_yaml
from app.modules.contrack_environments.config import EnvironmentError, load_settings
from app.modules.contrack_environments.war_deployment import DeployWarRequest, WarDeploymentService


class WarDeploymentTests(EnvironmentTestCase):
    def setUp(self):
        super().setUp()
        self.settings = self.settings.model_copy(update={"operation_mode": "deploy_war"})
        self.server = self.settings.path("server")
        (self.server / "conf").mkdir(parents=True)
        (self.server / "conf/server.xml").write_bytes(b"<Server>existing Tomcat configuration</Server>")
        (self.server / "conf/application.properties").write_bytes(b"db=existing-db\nrepository=existing-repo\n")
        (self.server / "conf/keystore.bin").write_bytes(b"\x00\xff\xfe\x80")
        (self.server / "webapps/contrack").mkdir(parents=True)
        (self.server / "webapps/contrack/existing.jsp").write_bytes(b"preserve exploded application")
        (self.server / "webapps/other.war").write_bytes(b"preserve other application")
        self.target = self.server / "webapps/contrack.war"
        self.target.write_bytes(b"previous WAR")
        self.deployment = WarDeploymentService(self.settings)
        self.payload = DeployWarRequest(war_id="WAR-520-release")

    def deploy(self):
        state, source, lock = self.deployment.begin(self.payload, "war-demo-user")
        self.deployment.execute(state, source, lock)
        return self.deployment.history.get(state["run_id"])

    def test_deploy_changes_only_target_war_and_preserves_conf_database_repository_and_other_webapps(self):
        before = {p: p.read_bytes() for p in self.server.rglob("*") if p.is_file() and p != self.target}
        source = self.root / "catalog/wars/5.2.0/release/contrack.war"
        source_bytes = source.read_bytes()
        with patch("subprocess.run", side_effect=AssertionError("WAR copy must not run DB/server commands")):
            run = self.deploy()
        self.assertEqual(run["status"], "DEPLOYED")
        self.assertEqual(run["application_status"], "NOT_CHECKED")
        self.assertIsNone(run["working_database"])
        self.assertEqual(self.target.read_bytes(), source_bytes)
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertTrue(all(p.read_bytes() == value for p, value in before.items()))
        self.assertEqual(set(self.server.rglob("*")), set(before) | {self.target, self.server / "conf", self.server / "webapps", self.server / "webapps/contrack"})
        current = self.deployment.runtime.get_current_environment()
        self.assertEqual(current["status"], "DEPLOYED")
        self.assertNotIn("health", current)
        self.assertFalse(EnvironmentLock.busy(self.settings.path("lock")))

    def test_app_war_in_flat_version_catalog_is_selected_and_deployed_as_app_war(self):
        manifest = read_yaml(self.root / "catalog/wars/5.2.0/release/manifest.yaml")
        manifest["war_id"] = "WAR-520-APP"
        manifest["artifact"]["file"] = "app.war"
        folder = self.root / "catalog/wars/5.2.0"
        write_yaml(folder / "manifest.yaml", manifest)
        (folder / "app.war").write_bytes(b"correct app WAR")
        (folder / "contrack.war").write_bytes(b"wrong WAR must not be selected")
        self.payload = DeployWarRequest(war_id="WAR-520-APP")
        preview = self.deployment.validate(self.payload)
        self.assertEqual(preview["source_file"], "app.war")
        self.assertEqual(preview["destination"], "runtime/server/webapps/app.war")
        run = self.deploy()
        self.assertEqual(run["status"], "DEPLOYED")
        self.assertEqual((self.target.parent / "app.war").read_bytes(), b"correct app WAR")
        self.assertEqual(self.target.read_bytes(), b"previous WAR")
        self.assertEqual((folder / "app.war").read_bytes(), b"correct app WAR")
        self.assertEqual(run["recipe"]["destination"], "runtime/server/webapps/app.war")
        self.assertIn("Copying app.war to runtime/server/webapps/app.war", run["log"])
        item = next(item for item in self.deployment.list_wars() if item["id"] == "WAR-520-APP")
        self.assertEqual(item["filename"], "app.war")
        self.assertEqual(item["destination"], preview["destination"])

    def test_artifact_subdirectory_does_not_create_subdirectories_in_webapps(self):
        path = self.root / "catalog/wars/5.2.0/release/manifest.yaml"
        manifest = read_yaml(path)
        manifest["artifact"]["file"] = "packages/app.war"
        write_yaml(path, manifest)
        (path.parent / "packages").mkdir()
        (path.parent / "packages/app.war").write_bytes(b"nested catalog app")
        self.assertEqual(self.deploy()["status"], "DEPLOYED")
        self.assertEqual((self.target.parent / "app.war").read_bytes(), b"nested catalog app")
        self.assertFalse((self.target.parent / "packages").exists())

    def test_war_only_catalog_does_not_require_or_parse_database_repository_or_bundle_manifests(self):
        (self.root / "catalog/bundles/520-release.yaml").write_text("invalid: bundle")
        (self.root / "catalog/databases/5.2.0/standard-v1/manifest.yaml").write_text("invalid: DB")
        (self.root / "catalog/repositories/svn/standard-v1/manifest.yaml").write_text("invalid: repository")
        self.assertEqual(len(self.deployment.list_wars()), 3)
        self.assertEqual(self.deploy()["status"], "DEPLOYED")

    def test_invalid_manifest_reports_field_without_echoing_its_value(self):
        path = self.root / "catalog/wars/5.2.0/release/manifest.yaml"
        manifest = read_yaml(path)
        manifest["build_id"] = 123
        manifest["password"] = "secret-do-not-echo"
        write_yaml(path, manifest)
        with self.assertRaises(EnvironmentError) as caught:
            VersionCatalogService(self.settings, wars_only=True)
        message = str(caught.exception)
        self.assertIn("build_id: must be a string", message)
        self.assertIn("password: unsupported field", message)
        self.assertNotIn("secret-do-not-echo", message)

    def test_invalid_yaml_reports_line_and_column_without_source_text(self):
        path = self.root / "catalog/wars/5.2.0/release/manifest.yaml"
        path.write_text('war_id: "unterminated-secret\n', encoding="utf-8")
        with self.assertRaises(EnvironmentError) as caught:
            VersionCatalogService(self.settings, wars_only=True)
        self.assertIn("Invalid YAML at line", str(caught.exception))
        self.assertNotIn("unterminated-secret", str(caught.exception))

    def test_failed_copy_preserves_previous_war_and_releases_lock(self):
        previous = self.target.read_bytes()
        with patch("app.modules.contrack_environments.war_deployment.shutil.copyfileobj", side_effect=OSError("disk full")):
            run = self.deploy()
        self.assertEqual(run["status"], "FAILED")
        self.assertFalse(run["war_copied"])
        self.assertEqual(self.target.read_bytes(), previous)
        self.assertEqual(list(self.target.parent.glob("*.tmp")), [])
        self.assertFalse(EnvironmentLock.busy(self.settings.path("lock")))

    def test_os_failures_identify_exact_operation_and_errno_without_echoing_exception_values(self):
        cases = [(errno.EACCES, "WAR_PERMISSION_DENIED"), (errno.ENOSPC, "WAR_STORAGE_FULL"),
                 (errno.EROFS, "WAR_READ_ONLY"), (getattr(errno, "EDQUOT", 122), "WAR_QUOTA_EXCEEDED")]
        for number, code in cases:
            with self.subTest(errno=number), \
                    patch("app.modules.contrack_environments.war_deployment.shutil.copyfileobj", side_effect=OSError(number, "secret-do-not-echo")), \
                    self.assertLogs("app.modules.contrack_environments.war_deployment", level="ERROR") as logs:
                run = self.deploy()
            self.assertEqual(run["error"]["code"], code)
            self.assertEqual(run["failed_operation"], "copy WAR bytes")
            self.assertIn(errno.errorcode[number], run["error"]["message"])
            self.assertNotIn("secret-do-not-echo", run["error"]["message"])
            self.assertNotIn("secret-do-not-echo", "\n".join(logs.output))
            self.assertEqual(self.target.read_bytes(), b"previous WAR")
            self.assertFalse(EnvironmentLock.busy(self.settings.path("lock")))

    def test_error_still_releases_lock_when_failure_state_cannot_be_written(self):
        state, source, lock = self.deployment.begin(self.payload, "disk-full-test")
        with patch.object(self.deployment.history, "save", side_effect=OSError(errno.ENOSPC, "disk full")), \
                self.assertLogs("app.modules.contrack_environments.war_deployment", level="ERROR") as logs:
            self.deployment.execute(state, source, lock)
        self.assertTrue(any("WAR_STORAGE_FULL" in entry for entry in logs.output))
        self.assertFalse(EnvironmentLock.busy(self.settings.path("lock")))
        self.assertEqual(self.target.read_bytes(), b"previous WAR")

    def test_storage_probe_cleans_its_files_and_keeps_existing_war_and_conf_unchanged(self):
        before = {path: path.read_bytes() for path in self.server.rglob("*") if path.is_file()}
        script = Path(__file__).resolve().parents[2] / "deploy/contrack-environments/check-war-storage.py"
        output = io.StringIO()
        with patch("app.modules.contrack_environments.config.load_settings", return_value=self.settings), \
                patch.object(os, "getuid", return_value=1000, create=True), \
                patch.object(os, "getgid", return_value=1000, create=True), \
                patch.object(os, "statvfs", return_value=SimpleNamespace(f_favail=100, f_flag=0), create=True), \
                patch("shutil.disk_usage", return_value=SimpleNamespace(free=1024 * 1024)), \
                redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            runpy.run_path(str(script), run_name="__main__")
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn("PASS: create / chmod / write / fsync / rename", output.getvalue())
        self.assertEqual(before, {path: path.read_bytes() for path in self.server.rglob("*") if path.is_file()})

    def test_storage_probe_explains_wrong_config_or_missing_mount_without_creating_directories(self):
        script = Path(__file__).resolve().parents[2] / "deploy/contrack-environments/check-war-storage.py"
        cases = [(self.settings.model_copy(update={"enabled": False}), "has not loaded enabled Deploy WAR"),
                 (self.settings.model_copy(update={"root": self.root / "not-mounted"}), "webapps directory is missing")]
        for settings, expected in cases:
            output = io.StringIO()
            with self.subTest(expected=expected), \
                    patch("app.modules.contrack_environments.config.load_settings", return_value=settings), \
                    redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
                runpy.run_path(str(script), run_name="__main__")
            self.assertEqual(stopped.exception.code, 2)
            self.assertIn(expected, output.getvalue())
        self.assertFalse((self.root / "not-mounted").exists())

    def test_failed_atomic_replace_restores_previous_published_state(self):
        self.deploy()
        previous = self.deployment.runtime.get_current_environment()
        old_bytes = self.target.read_bytes()
        with patch("app.modules.contrack_environments.war_deployment.replace_war", side_effect=PermissionError("locked")):
            run = self.deploy()
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(self.target.read_bytes(), old_bytes)
        self.assertEqual(self.deployment.runtime.get_current_environment()["run_id"], previous["run_id"])
        self.assertEqual(self.deployment.runtime.get_current_environment()["status"], "DEPLOYED")
        self.assertFalse(EnvironmentLock.busy(self.settings.path("lock")))

    def test_war_mutation_after_selection_does_not_overwrite_runtime(self):
        state, source, lock = self.deployment.begin(self.payload, "test")
        source.write_bytes(b"changed source")
        self.deployment.execute(state, source, lock)
        run = self.deployment.history.get(state["run_id"])
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["error"]["code"], "CHECKSUM_MISMATCH")
        self.assertEqual(self.target.read_bytes(), b"previous WAR")

    def test_pasted_duplicate_state_reports_file_and_line_before_creating_a_deployment(self):
        path = self.settings.path("current") / "version.yaml"
        path.parent.mkdir(parents=True)
        original = ('bundle: "CT-5.2.0-HF8383"\nwar: "WAR-5.2.0-HF8383-001"\n'
                    'database: "DB-520-LARGE-V1"\nrepository: "SVN-LARGE-V1"bundle: "CT-5.2.0-HF8383"\n')
        path.write_text(original, encoding="utf-8")
        for action in (lambda: self.deployment.validate(self.payload),
                       lambda: self.deployment.begin(self.payload, "test")):
            with self.assertRaises(EnvironmentError) as caught:
                action()
            self.assertEqual(caught.exception.code, "INVALID_STATE_YAML")
            self.assertIn(str(path), str(caught.exception))
            self.assertIn("line 4", str(caught.exception))
            self.assertNotIn("SVN-LARGE-V1", str(caught.exception))
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(self.target.read_bytes(), b"previous WAR")
        self.assertFalse(self.settings.path("runs").exists())
        self.assertFalse(EnvironmentLock.busy(self.settings.path("lock")))

    def test_corrupt_referenced_run_state_is_identified_without_touching_war(self):
        run = self.deploy()
        current = self.deployment.runtime.get_current_environment()
        self.deployment.runtime.save({**current, "status": "RUNNING"})
        path = self.deployment.history.directory(run["run_id"]) / "state.yaml"
        path.write_text('status: "unterminated\n', encoding="utf-8")
        previous = self.target.read_bytes()
        with self.assertRaises(EnvironmentError) as caught:
            self.deployment.validate(self.payload)
        self.assertEqual(caught.exception.code, "INVALID_STATE_YAML")
        self.assertIn(str(path), str(caught.exception))
        self.assertEqual(self.target.read_bytes(), previous)

    def test_invalid_existing_server_and_arbitrary_path_inputs_are_rejected(self):
        self.assert_error("INVALID_ID", lambda: self.deployment.validate(DeployWarRequest(war_id="../outside")))
        (self.server / "conf/server.xml").unlink()
        self.assert_error("EXISTING_TOMCAT_REQUIRED", lambda: self.deployment.validate(self.payload))
        self.assertEqual(self.target.read_bytes(), b"previous WAR")

    def test_validate_has_no_deployment_or_history_side_effects(self):
        result = self.deployment.validate(self.payload)
        self.assertTrue(result["valid"])
        self.assertEqual(self.target.read_bytes(), b"previous WAR")
        self.assertFalse(self.settings.path("runs").exists())
        self.assertFalse(self.settings.path("lock").exists())

    def test_bound_root_overrides_stale_yaml_root_for_actual_war_deployment(self):
        config = self.root / "environment.yaml"
        write_yaml(config, {"enabled": True, "operation_mode": "deploy_war", "root": str(self.root / "wrong-root")})
        with patch.dict(os.environ, {"CONTRACK_ENV_CONFIG": str(config), "CONTRACK_ENV_ROOT": str(self.root)}):
            settings = load_settings()
        self.assertEqual(settings.root, self.root)
        service = WarDeploymentService(settings)
        state, source, lock = service.begin(self.payload, "root-test")
        service.execute(state, source, lock)
        self.assertEqual(service.history.get(state["run_id"])["status"], "DEPLOYED")
        self.assertEqual(self.target.read_bytes(), source.read_bytes())
        self.assertFalse((self.root / "wrong-root").exists())

    def test_switch_lock_is_shared_with_full_environment_preparation(self):
        state, source, lock = self.deployment.begin(self.payload, "user-a")
        try:
            self.assert_error("ENVIRONMENT_BUSY", lambda: self.deployment.begin(self.payload, "user-b"))
            full = EnvironmentPreparationService(self.settings.model_copy(update={"operation_mode": "prepare_environment"}))
            self.assert_error("ENVIRONMENT_BUSY", lambda: full.begin(PrepareRequest(bundle_id="CT-520-release"), "user-c"))
        finally:
            lock.release()

    def test_wrong_operation_mode_cannot_prepare_working_database(self):
        full = EnvironmentPreparationService(self.settings)
        self.assert_error("OPERATION_MODE", lambda: full.begin(PrepareRequest(bundle_id="CT-520-release"), "test"))
        self.assert_error("OPERATION_MODE", lambda: full.validate(PrepareRequest(bundle_id="CT-520-release")))
        normal = WarDeploymentService(self.settings.model_copy(update={"operation_mode": "prepare_environment"}))
        self.assert_error("DEPLOY_WAR_DISABLED", lambda: normal.begin(self.payload, "test"))

    def test_api_catalog_and_war_deployment(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from types import SimpleNamespace
        from app.modules.contrack_environments.router import get_service, router
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[get_service] = lambda: EnvironmentPreparationService(self.settings)
        for route in router.routes:
            for dependency in route.dependant.dependencies:
                if dependency.call is not get_service:
                    app.dependency_overrides[dependency.call] = lambda: SimpleNamespace(username="api-war-demo")
        client = TestClient(app)
        base = "/api/contrack-environments"
        catalog = client.get(base + "/catalog").json()
        self.assertEqual(catalog["operation_mode"], "deploy_war")
        self.assertEqual(len(catalog["wars"]), 3)
        response = client.post(base + "/wars/deploy", json={"war_id": self.payload.war_id})
        self.assertEqual(response.status_code, 202)
        run = client.get(base + "/runs/" + response.json()["run_id"]).json()
        self.assertEqual(run["status"], "DEPLOYED")
        self.assertEqual(client.post(base + "/prepare", json={"bundle_id": "CT-520-release"}).status_code, 409)
