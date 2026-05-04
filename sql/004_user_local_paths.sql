ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS build_source_folder TEXT,
    ADD COLUMN IF NOT EXISTS build_output_folder TEXT,
    ADD COLUMN IF NOT EXISTS git_eol_source_folder TEXT;
