ALTER TABLE user_settings
ADD COLUMN IF NOT EXISTS box_access_token_enc TEXT;

ALTER TABLE user_settings
ADD COLUMN IF NOT EXISTS box_refresh_token_enc TEXT;

ALTER TABLE user_settings
ADD COLUMN IF NOT EXISTS box_token_expires_at TIMESTAMPTZ;
