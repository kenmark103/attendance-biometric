-- 010_entra_auth_wfh: Viewer/Admin auth model, bounded sessions, and WFH policies.
-- Apply with: psql "$DATABASE_URL" -f db/migrations/010_entra_auth_wfh.sql
-- Revert with: psql "$DATABASE_URL" -f db/migrations/010_entra_auth_wfh.down.sql
BEGIN;

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
-- The former manager role was never used. Normalize safely before narrowing
-- the database constraint; unexpected historical values fail closed as Viewer.
UPDATE users
SET role = CASE lower(role)
    WHEN 'admin' THEN 'Admin'
    WHEN 'viewer' THEN 'Viewer'
    ELSE 'Viewer'
END;
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'Viewer';
ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('Viewer', 'Admin'));

-- Session families store their original-login time and provider explicitly.
ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS family_started_at TIMESTAMPTZ;
ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS auth_provider TEXT;
ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ;
ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
UPDATE refresh_tokens r
SET family_started_at = COALESCE(r.family_started_at, r.issued_at, now()),
    created_at = COALESCE(r.created_at, r.issued_at, now()),
    last_used_at = COALESCE(r.last_used_at, r.issued_at),
    auth_provider = COALESCE(r.auth_provider, u.auth_provider)
FROM users u WHERE u.id = r.user_id;
ALTER TABLE refresh_tokens ALTER COLUMN family_started_at SET NOT NULL;
ALTER TABLE refresh_tokens ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE refresh_tokens ALTER COLUMN auth_provider SET NOT NULL;
ALTER TABLE refresh_tokens DROP CONSTRAINT IF EXISTS refresh_tokens_auth_provider_check;
ALTER TABLE refresh_tokens ADD CONSTRAINT refresh_tokens_auth_provider_check
    CHECK (auth_provider IN ('local', 'entra'));
ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS family_expires_at;
ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS issued_at;

-- Auth-event names become durable audit vocabulary.
ALTER TABLE auth_events RENAME COLUMN at TO ts;
ALTER TABLE auth_events RENAME COLUMN provider TO method;
ALTER TABLE auth_events ADD COLUMN IF NOT EXISTS entra_oid TEXT;
UPDATE auth_events SET event = CASE event
    WHEN 'login_ok' THEN 'login_success'
    WHEN 'login_fail' THEN 'login_failed'
    WHEN 'sso_ok' THEN 'login_success'
    WHEN 'sso_denied' THEN 'login_denied_no_role'
    WHEN 'refresh_reuse' THEN 'refresh_reuse_detected'
    ELSE event
END;
ALTER TABLE auth_events DROP CONSTRAINT IF EXISTS auth_events_method_check;
ALTER TABLE auth_events ADD CONSTRAINT auth_events_method_check
    CHECK (method IN ('local', 'entra') OR method IS NULL);
CREATE INDEX IF NOT EXISTS idx_auth_events_ts ON auth_events (ts DESC);
CREATE INDEX IF NOT EXISTS idx_auth_events_email ON auth_events (email);

-- General audit rows retain old employee targets as generic entity data.
ALTER TABLE audit_log RENAME COLUMN created_at TO ts;
ALTER TABLE audit_log RENAME COLUMN before_value TO before;
ALTER TABLE audit_log RENAME COLUMN after_value TO after;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS actor_email TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS entity_type TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS entity_id TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS request_id TEXT;
UPDATE audit_log
SET entity_type = COALESCE(entity_type, CASE WHEN target_employee_id IS NOT NULL THEN 'employee' END),
    entity_id = COALESCE(entity_id, target_employee_id);
ALTER TABLE audit_log DROP COLUMN IF EXISTS target_employee_id;
CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log (ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log (actor_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log (entity_type, entity_id);

-- Empty legacy stub verified before this migration. Its down migration restores
-- only the empty schema; data cannot be lost because the table was empty.
DROP TABLE IF EXISTS wfh_approvals;

CREATE TABLE wfh_policies (
    id SERIAL PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(id),
    type TEXT NOT NULL CHECK (type IN ('temporary', 'default')),
    start_date DATE NOT NULL,
    end_date DATE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'revoked')),
    note TEXT,
    created_by UUID REFERENCES users(id),
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT wfh_temporary_dates CHECK (type <> 'temporary' OR end_date IS NOT NULL AND end_date >= start_date)
);
CREATE INDEX idx_wfh_policies_employee_dates ON wfh_policies (employee_id, start_date, end_date);
CREATE INDEX idx_wfh_policies_status ON wfh_policies (status);

CREATE TABLE wfh_recalls (
    id SERIAL PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(id),
    date DATE NOT NULL,
    reason TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (employee_id, date)
);
CREATE INDEX idx_wfh_recalls_date ON wfh_recalls (date);

COMMIT;
