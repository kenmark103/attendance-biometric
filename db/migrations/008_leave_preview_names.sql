-- 008_leave_preview_names: preview-scoped employee names + re-uploadable hashes.
-- Apply if DB already initialized before this commit:
-- psql $DATABASE_URL -f db/migrations/008_leave_preview_names.sql
--
-- preview_names holds the file's employee_id -> name map for the in-flight
-- preview ONLY (Unmatched-employees tab, name-mismatch check). It is nulled
-- on commit/discard/expiry and never read by the attendance overlay.
-- The full UNIQUE on file_sha256 becomes partial so a failed/discarded/
-- expired/reverted file can be re-uploaded, while a committed (or live
-- preview) file stays a no-op.
ALTER TABLE leave_import ADD COLUMN IF NOT EXISTS preview_names JSONB;

ALTER TABLE leave_import DROP CONSTRAINT IF EXISTS leave_import_file_sha256_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_leave_import_sha_live
    ON leave_import (file_sha256)
    WHERE status IN ('parsing', 'preview_ready', 'committing', 'committed');
