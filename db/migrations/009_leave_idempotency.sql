-- 009_leave_idempotency: safe commit retries via client-supplied key.
-- Apply if DB already initialized before this commit:
-- psql $DATABASE_URL -f db/migrations/009_leave_idempotency.sql
ALTER TABLE leave_import ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_leave_import_idem
    ON leave_import (idempotency_key) WHERE idempotency_key IS NOT NULL;
