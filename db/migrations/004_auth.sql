-- 004_auth: Entra SSO + local email/password auth (see Auth Implementation Guide).
-- Apply if DB already initialized before this commit:
--   psql $DATABASE_URL -f db/migrations/004_auth.sql
-- Fresh installs use db/init.sql directly (already at final schema).

-- UUID generation is built into PG16, no extension needed.

-- 1+3+4. One-time legacy conversion. Runs only while the old app_users
-- table still exists; on re-runs (or fresh installs, which use init.sql)
-- this block is a no-op. Google rows are test data and are dropped.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_tables
               WHERE schemaname = 'public' AND tablename = 'app_users') THEN
        DELETE FROM app_users WHERE provider = 'google';

        INSERT INTO users (email, display_name, role, auth_provider, entra_oid,
                           is_active, must_change_password, last_login_at, created_at)
        SELECT lower(trim(email)),
               name,
               CASE WHEN role = 'management' THEN 'manager'
                    WHEN role IN ('admin', 'manager', 'viewer') THEN role
                    ELSE 'viewer' END,
               CASE WHEN provider = 'entra' THEN 'entra' ELSE 'local' END,
               CASE WHEN provider = 'entra' THEN NULLIF(provider_user_id, '') ELSE NULL END,
               TRUE,
               -- local rows keep NULL hash + must_change_password so an admin sets a real one
               CASE WHEN provider = 'entra' THEN FALSE ELSE TRUE END,
               last_login_at,
               created_at
        FROM app_users
        ON CONFLICT (email) DO NOTHING;

        -- Point audit/approval actor columns at users (UUID). Old integer
        -- actor values are dev-test data and cannot map to new UUIDs, so nulled.
        ALTER TABLE wfh_approvals DROP CONSTRAINT IF EXISTS wfh_approvals_approved_by_fkey;
        ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_actor_user_id_fkey;

        ALTER TABLE wfh_approvals ADD COLUMN IF NOT EXISTS approved_by_uuid UUID;
        UPDATE wfh_approvals SET approved_by_uuid = NULL;
        ALTER TABLE wfh_approvals DROP COLUMN IF EXISTS approved_by;
        ALTER TABLE wfh_approvals RENAME COLUMN approved_by_uuid TO approved_by;
        ALTER TABLE wfh_approvals
            ADD CONSTRAINT wfh_approvals_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES users(id);

        ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS actor_uuid UUID;
        UPDATE audit_log SET actor_uuid = NULL;
        ALTER TABLE audit_log DROP COLUMN IF EXISTS actor_user_id;
        ALTER TABLE audit_log RENAME COLUMN actor_uuid TO actor_user_id;
        ALTER TABLE audit_log
            ADD CONSTRAINT audit_log_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES users(id);

        DROP TABLE app_users;
    END IF;
END
$$;

-- 2. New users table (replaces app_users, distinct from employees).
CREATE TABLE IF NOT EXISTS users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               TEXT UNIQUE NOT NULL,
    display_name        TEXT,
    role                TEXT NOT NULL DEFAULT 'viewer'
                        CHECK (role IN ('admin', 'manager', 'viewer')),
    auth_provider       TEXT NOT NULL DEFAULT 'local'
                        CHECK (auth_provider IN ('local', 'entra')),
    password_hash       TEXT,
    entra_oid           TEXT UNIQUE,
    entra_tid           TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    failed_login_count  INTEGER NOT NULL DEFAULT 0,
    locked_until        TIMESTAMPTZ,
    last_login_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_entra_oid ON users (entra_oid);

-- 5. Refresh-token families (opaque token stored as SHA-256 hash).
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id         UUID NOT NULL,
    token_hash        TEXT UNIQUE NOT NULL,
    issued_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at        TIMESTAMPTZ NOT NULL,
    family_expires_at TIMESTAMPTZ NOT NULL,
    revoked_at        TIMESTAMPTZ,
    replaced_by       UUID REFERENCES refresh_tokens(id),
    user_agent        TEXT,
    ip                TEXT
);
CREATE INDEX IF NOT EXISTS idx_refresh_family ON refresh_tokens (family_id);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens (user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_hash ON refresh_tokens (token_hash);

-- 6. Auth audit trail. Never stores passwords or token hashes.
CREATE TABLE IF NOT EXISTS auth_events (
    id         SERIAL PRIMARY KEY,
    at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id    UUID REFERENCES users(id) ON DELETE SET NULL,
    email      TEXT,
    event      TEXT NOT NULL,
    provider   TEXT,
    ip         TEXT,
    user_agent TEXT,
    detail     TEXT
);
CREATE INDEX IF NOT EXISTS idx_auth_events_at ON auth_events (at DESC);
