ALTER TABLE notes ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE notes ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0;

-- Set initial positions based on created_at order
WITH ranked AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY created_at ASC) - 1 AS rn FROM notes
)
UPDATE notes SET position = ranked.rn FROM ranked WHERE notes.id = ranked.id;
