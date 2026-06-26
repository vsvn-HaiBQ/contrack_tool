-- Baseline folders are Box folder ids, same shape as client/server folder ids.
ALTER TABLE versions
    ALTER COLUMN client_baseline_folder TYPE VARCHAR(100),
    ALTER COLUMN server_baseline_folder TYPE VARCHAR(100);

-- Box folder ids now live on each version, not on global settings.
ALTER TABLE box_integration_settings DROP COLUMN IF EXISTS client_folder_id;
ALTER TABLE box_integration_settings DROP COLUMN IF EXISTS server_folder_id;

-- default_base_branch moved to per-version configuration.
DELETE FROM system_settings WHERE key = 'default_base_branch';
