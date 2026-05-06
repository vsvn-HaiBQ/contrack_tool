CREATE TABLE IF NOT EXISTS box_integration_settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    client_id TEXT,
    client_secret_enc TEXT,
    server_folder_id VARCHAR(100),
    client_folder_id VARCHAR(100),
    shared_link_access VARCHAR(20),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(100),
    CONSTRAINT ck_box_integration_settings_singleton CHECK (id = 1)
);

INSERT INTO box_integration_settings (id, shared_link_access)
VALUES (1, 'company')
ON CONFLICT (id) DO NOTHING;
