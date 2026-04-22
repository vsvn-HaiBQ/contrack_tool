CREATE TABLE IF NOT EXISTS user_managed_ticket_follows (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    managed_ticket_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_user_managed_ticket_follows_user
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_user_managed_ticket_follows_managed_ticket
        FOREIGN KEY (managed_ticket_id)
        REFERENCES managed_tickets(id)
        ON DELETE CASCADE,
    CONSTRAINT uq_user_managed_ticket_follows_user_ticket UNIQUE (user_id, managed_ticket_id)
);

CREATE INDEX IF NOT EXISTS idx_user_managed_ticket_follows_user_id
    ON user_managed_ticket_follows (user_id);

CREATE INDEX IF NOT EXISTS idx_user_managed_ticket_follows_managed_ticket_id
    ON user_managed_ticket_follows (managed_ticket_id);
