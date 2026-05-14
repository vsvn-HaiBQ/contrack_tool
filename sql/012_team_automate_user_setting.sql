ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS team_automate_url_enc TEXT;
