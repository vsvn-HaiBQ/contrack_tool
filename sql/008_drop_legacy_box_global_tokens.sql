ALTER TABLE box_integration_settings
DROP COLUMN IF EXISTS access_token_enc;

ALTER TABLE box_integration_settings
DROP COLUMN IF EXISTS refresh_token_enc;

ALTER TABLE box_integration_settings
DROP COLUMN IF EXISTS token_expires_at;
