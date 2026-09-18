"""Processor preference validation and persistence without an external database."""
import os
import unittest

os.environ["CONTRACK_DATABASE_URL"] = "sqlite://"

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import UserSettings
from app.modules.users.service import (
    apply_document_translation_settings,
    serialize_document_translation_settings,
)
from app.schemas import DocumentTranslationSettingsIn


class DocumentTranslationSettingsTests(unittest.TestCase):
    def test_old_accounts_default_to_filehandler(self):
        settings = UserSettings(user_id=1)
        self.assertEqual(serialize_document_translation_settings(settings).file_processor, "filehandler")

    def test_processor_round_trip_and_partial_updates(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        UserSettings.__table__.create(engine)
        with Session(engine) as db:
            settings = UserSettings(user_id=1)
            db.add(settings)
            for processor in ("openxml", "filehandler"):
                payload = DocumentTranslationSettingsIn(file_processor=processor)
                apply_document_translation_settings(settings, **payload.model_dump(exclude_unset=True))
                db.commit()
                db.expire_all()
                saved = db.get(UserSettings, 1)
                self.assertEqual(serialize_document_translation_settings(saved).file_processor, processor)
                apply_document_translation_settings(saved, glossary="source => target")
                self.assertEqual(saved.document_translation_file_processor, processor)

    def test_null_resets_default_and_invalid_selection_is_rejected(self):
        settings = UserSettings(user_id=1, document_translation_file_processor="openxml")
        apply_document_translation_settings(settings, file_processor=None)
        self.assertEqual(settings.document_translation_file_processor, "filehandler")
        for value in ("unknown", "", 1):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                DocumentTranslationSettingsIn(file_processor=value)
        with self.assertRaises(ValueError):
            apply_document_translation_settings(settings, file_processor="unknown")


if __name__ == "__main__":
    unittest.main()
