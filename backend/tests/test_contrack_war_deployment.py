from pathlib import Path
from unittest.mock import patch

from test_contrack_environments import EnvironmentTestCase
from app.modules.contrack_environments.catalog import PrepareRequest
from app.modules.contrack_environments.service import EnvironmentPreparationService
from app.modules.contrack_environments.state import EnvironmentLock, read_yaml
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

    def test_war_only_catalog_does_not_require_or_parse_database_repository_or_bundle_manifests(self):
        (self.root / "catalog/bundles/520-release.yaml").write_text("invalid: bundle")
        (self.root / "catalog/databases/5.2.0/standard-v1/manifest.yaml").write_text("invalid: DB")
        (self.root / "catalog/repositories/svn/standard-v1/manifest.yaml").write_text("invalid: repository")
        self.assertEqual(len(self.deployment.list_wars()), 3)
        self.assertEqual(self.deploy()["status"], "DEPLOYED")

    def test_failed_copy_preserves_previous_war_and_releases_lock(self):
        previous = self.target.read_bytes()
        with patch("app.modules.contrack_environments.war_deployment.shutil.copyfileobj", side_effect=OSError("disk full")):
            run = self.deploy()
        self.assertEqual(run["status"], "FAILED")
        self.assertFalse(run["war_copied"])
        self.assertEqual(self.target.read_bytes(), previous)
        self.assertEqual(list(self.target.parent.glob("*.tmp")), [])
        self.assertFalse(EnvironmentLock.busy(self.settings.path("lock")))

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
