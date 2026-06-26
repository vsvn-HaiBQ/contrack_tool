CREATE TABLE IF NOT EXISTS versions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    default_base_branch VARCHAR(200),
    client_folder_id VARCHAR(100),
    server_folder_id VARCHAR(100),
    client_baseline_folder TEXT,
    server_baseline_folder TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_versions_position ON versions(position, id);

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS pinned_version_id INTEGER REFERENCES versions(id) ON DELETE SET NULL;
