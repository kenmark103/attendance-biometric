-- Revert 010_entra_auth_wfh. The legacy WFH table was verified empty before
-- the forward migration, so this intentionally recreates an empty stub only.
BEGIN;
DROP TABLE IF EXISTS wfh_recalls;
DROP TABLE IF EXISTS wfh_policies;
CREATE TABLE IF NOT EXISTS wfh_approvals (
    id SERIAL PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(id),
    date DATE NOT NULL,
    approved_by UUID REFERENCES users(id),
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (employee_id, date)
);
CREATE INDEX IF NOT EXISTS idx_wfh_employee_date ON wfh_approvals (employee_id, date);
CREATE INDEX IF NOT EXISTS idx_wfh_date ON wfh_approvals (date);

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS target_employee_id TEXT;
UPDATE audit_log SET target_employee_id = entity_id WHERE entity_type = 'employee';
ALTER TABLE audit_log RENAME COLUMN ts TO created_at;
ALTER TABLE audit_log RENAME COLUMN before TO before_value;
ALTER TABLE audit_log RENAME COLUMN after TO after_value;
ALTER TABLE audit_log DROP COLUMN IF EXISTS request_id;
ALTER TABLE audit_log DROP COLUMN IF EXISTS ip;
ALTER TABLE audit_log DROP COLUMN IF EXISTS entity_id;
ALTER TABLE audit_log DROP COLUMN IF EXISTS entity_type;
ALTER TABLE audit_log DROP COLUMN IF EXISTS actor_email;

ALTER TABLE auth_events RENAME COLUMN ts TO at;
ALTER TABLE auth_events RENAME COLUMN method TO provider;
ALTER TABLE auth_events DROP COLUMN IF EXISTS entra_oid;

ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS issued_at TIMESTAMPTZ;
ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS family_expires_at TIMESTAMPTZ;
UPDATE refresh_tokens SET issued_at = created_at, family_expires_at = expires_at;
ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS last_used_at;
ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS auth_provider;
ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS family_started_at;
ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS created_at;

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
UPDATE users SET role = lower(role);
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'viewer';
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('admin', 'manager', 'viewer'));
COMMIT;
