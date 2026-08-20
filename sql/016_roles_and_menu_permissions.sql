CREATE TABLE IF NOT EXISTS roles (
    name VARCHAR(100) PRIMARY KEY,
    permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO roles (name, permissions)
VALUES
    ('admin', '["ticket_detail", "ticket_sync", "pull_requests", "git_eol", "build_source", "confluence_preview", "document_translation", "logtime", "notes", "audit"]'::jsonb),
    ('dev', '["ticket_detail", "ticket_sync", "pull_requests", "git_eol", "build_source", "confluence_preview", "document_translation", "logtime", "notes"]'::jsonb),
    ('qa', '["ticket_detail", "ticket_sync", "confluence_preview", "document_translation", "logtime", "notes"]'::jsonb)
ON CONFLICT (name) DO NOTHING;

ALTER TABLE users
    ALTER COLUMN role TYPE VARCHAR(100)
    USING role::text;

DROP TYPE IF EXISTS user_role;
