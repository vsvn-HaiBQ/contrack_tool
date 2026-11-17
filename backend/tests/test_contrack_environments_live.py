"""Explicitly opt-in integration test against operator-provided Linux infrastructure."""
import os
import unittest
from unittest.mock import patch

from app.modules.contrack_environments.catalog import PrepareRequest, VersionCatalogService, digest
from app.modules.contrack_environments.config import load_settings
from app.modules.contrack_environments.service import EnvironmentPreparationService


@unittest.skipUnless(os.environ.get("CT_ENV_LIVE_ALLOW_PREPARE") == "1" and os.environ.get("CT_ENV_LIVE_CONFIG"),
                     "Requires explicit opt-in and real Linux/Tomcat/PostgreSQL configuration")
class LiveEnvironmentSwitchTests(unittest.TestCase):
    def test_upgrade_hotfix_and_switch_back_to_older_baseline(self):
        ids = [os.environ.get(key) for key in ("CT_ENV_LIVE_510", "CT_ENV_LIVE_520", "CT_ENV_LIVE_HOTFIX")]
        self.assertTrue(all(ids), "Set CT_ENV_LIVE_510, CT_ENV_LIVE_520 and CT_ENV_LIVE_HOTFIX bundle IDs")
        with patch.dict(os.environ, {"CONTRACK_ENV_CONFIG": os.environ["CT_ENV_LIVE_CONFIG"]}):
            settings = load_settings()
        self.assertTrue(settings.enabled)
        catalog = VersionCatalogService(settings)
        paths = [catalog.resolve(PrepareRequest(bundle_id=id)).baseline_path for id in ids]
        before = {path: digest(path) for path in paths}
        service = EnvironmentPreparationService(settings)
        working_databases = []
        for bundle_id in [*ids, ids[0]]:
            with self.subTest(bundle=bundle_id):
                state, recipe, lock = service.begin(PrepareRequest(bundle_id=bundle_id), "live-integration-test")
                service.execute(state, recipe, lock)
                result = service.history.get(state["run_id"])
                self.assertEqual(result["status"], "READY", result.get("error"))
                self.assertEqual(service.runtime.get_current_environment()["bundle"], bundle_id)
                service.adapter.check_schema(state["working_database"], recipe.database.schema_version)
                working_databases.append(state["working_database"])
        self.assertEqual(len(set(working_databases)), 4)
        self.assertEqual({path: digest(path) for path in paths}, before)


if __name__ == "__main__":
    unittest.main()
