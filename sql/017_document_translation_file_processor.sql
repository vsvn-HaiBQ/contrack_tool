ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS document_translation_file_processor VARCHAR(20);
