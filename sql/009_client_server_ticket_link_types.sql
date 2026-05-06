ALTER TYPE ticket_link_type ADD VALUE IF NOT EXISTS 'client';

ALTER TYPE ticket_link_type ADD VALUE IF NOT EXISTS 'server';

CREATE UNIQUE INDEX IF NOT EXISTS uq_ticket_links_client_per_ticket
    ON ticket_links (managed_ticket_id)
    WHERE type = 'client';

CREATE UNIQUE INDEX IF NOT EXISTS uq_ticket_links_server_per_ticket
    ON ticket_links (managed_ticket_id)
    WHERE type = 'server';
