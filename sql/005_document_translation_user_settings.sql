ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS document_translation_output_directory TEXT,
    ADD COLUMN IF NOT EXISTS document_translation_direction VARCHAR(20),
    ADD COLUMN IF NOT EXISTS document_translation_model VARCHAR(100),
    ADD COLUMN IF NOT EXISTS document_translation_reasoning_effort VARCHAR(20),
    ADD COLUMN IF NOT EXISTS document_translation_timeout_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS document_translation_batch_size INTEGER,
    ADD COLUMN IF NOT EXISTS document_translation_context_window INTEGER,
    ADD COLUMN IF NOT EXISTS document_translation_fast_mode BOOLEAN,
    ADD COLUMN IF NOT EXISTS document_translation_glossary TEXT,
    ADD COLUMN IF NOT EXISTS document_translation_instructions TEXT;
