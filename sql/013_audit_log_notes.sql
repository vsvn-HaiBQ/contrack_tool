-- Add notes column to audit_logs table
ALTER TABLE audit_logs
ADD COLUMN IF NOT EXISTS notes TEXT;

CREATE INDEX IF NOT EXISTS idx_audit_logs_notes
    ON audit_logs (notes)
    WHERE notes IS NOT NULL;
