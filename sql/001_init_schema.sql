DO $$
BEGIN
    CREATE TYPE user_role AS ENUM ('admin', 'user');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE ticket_link_type AS ENUM ('spec', 'thread', 'build', 'pr');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    password_hash TEXT NOT NULL,
    role user_role NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_users_username UNIQUE (username)
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    redmine_jp_api_key_enc TEXT,
    redmine_vn_api_key_enc TEXT,
    github_token_enc TEXT,
    default_assignee_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_user_settings_user
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS system_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS managed_tickets (
    id SERIAL PRIMARY KEY,
    jp_issue_id INTEGER NOT NULL,
    vn_issue_id INTEGER NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_managed_tickets_jp_issue_id UNIQUE (jp_issue_id)
);

CREATE TABLE IF NOT EXISTS ticket_links (
    id SERIAL PRIMARY KEY,
    managed_ticket_id INTEGER NOT NULL,
    type ticket_link_type NOT NULL,
    label VARCHAR(255) NOT NULL,
    url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_ticket_links_managed_ticket
        FOREIGN KEY (managed_ticket_id)
        REFERENCES managed_tickets(id)
        ON DELETE CASCADE,
    CONSTRAINT uq_ticket_links_url UNIQUE (url)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    actor_user_id INTEGER,
    actor_username VARCHAR(100) NOT NULL,
    action VARCHAR(100) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_id VARCHAR(100),
    payload_before JSONB,
    payload_after JSONB,
    ip INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ticket_links_managed_ticket_id
    ON ticket_links (managed_ticket_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ticket_links_thread_per_ticket
    ON ticket_links (managed_ticket_id)
    WHERE type = 'thread';

CREATE UNIQUE INDEX IF NOT EXISTS uq_ticket_links_pr_per_ticket
    ON ticket_links (managed_ticket_id)
    WHERE type = 'pr';

CREATE INDEX IF NOT EXISTS idx_audit_logs_actor_user_id
    ON audit_logs (actor_user_id);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at
    ON audit_logs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_target
    ON audit_logs (target_type, target_id);

INSERT INTO system_settings (key, value) VALUES
    ('git_repo', NULL),
    ('redmine_jp_host', NULL),
    ('redmine_vn_host', NULL),
    ('redmine_vn_project_id', NULL),
    ('default_base_branch', NULL),
    ('description_template', NULL)
ON CONFLICT (key) DO NOTHING;
