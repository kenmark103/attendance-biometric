-- 005_cosec_delete_audit: diagnostic audit for DELETEs on COSEC staging.
-- Twice, staging rows vanished with no known actor (67k daily rows pruned to
-- the last 4 days, 55 users removed, scope flags wiped) while dashboard tables
-- were untouched. This trigger records WHEN it happens next (statement time
-- + row count) so it can be correlated with access. It does not block deletes.
-- TRUNCATE is not covered; use DELETE if you must remove rows.
-- Apply: psql $DATABASE_URL -f db/migrations/005_cosec_delete_audit.sql
-- Fresh installs: include via db/init.sql (appended at the end, guarded).

CREATE TABLE IF NOT EXISTS cosec_delete_audit (
    id              SERIAL PRIMARY KEY,
    at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    tbl             TEXT NOT NULL,
    rows_deleted    INTEGER NOT NULL
);

CREATE OR REPLACE FUNCTION log_cosec_delete() RETURNS trigger AS $$
BEGIN
    INSERT INTO cosec_delete_audit (tbl, rows_deleted)
    VALUES (TG_TABLE_NAME, (SELECT count(*) FROM old_table));
    RETURN NULL;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cosec_users_del ON cosec_users;
CREATE TRIGGER trg_cosec_users_del AFTER DELETE ON cosec_users
    REFERENCING OLD TABLE AS old_table
    FOR EACH STATEMENT EXECUTE FUNCTION log_cosec_delete();

DROP TRIGGER IF EXISTS trg_cosec_daily_del ON cosec_attendance_daily;
CREATE TRIGGER trg_cosec_daily_del AFTER DELETE ON cosec_attendance_daily
    REFERENCING OLD TABLE AS old_table
    FOR EACH STATEMENT EXECUTE FUNCTION log_cosec_delete();
