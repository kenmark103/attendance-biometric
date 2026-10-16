-- Attendance System — full schema (Phase 1)
-- Supersedes the earlier simplified local-dev version.
-- Design notes inline where a choice reflects an earlier discussion.

CREATE TABLE teams (
    id      SERIAL PRIMARY KEY,
    name    TEXT UNIQUE NOT NULL,
    lead_employee_id TEXT   -- FK added after employees exists (below)
);

CREATE TABLE employees (
    id              TEXT PRIMARY KEY,      -- Zoho employee id (same as biometric employee number)
    name            TEXT NOT NULL,
    current_team_id INTEGER REFERENCES teams(id),
    "current_role"  TEXT,                  -- quoted: current_role is a PG reserved keyword
    "current_shift" TEXT,                  -- 'day' | 'night' | 'hybrid' — unknown until Zoho gives it
    status          TEXT NOT NULL DEFAULT 'active'  -- 'active' | 'offboarded' — never hard-deleted
);

ALTER TABLE teams ADD CONSTRAINT fk_team_lead FOREIGN KEY (lead_employee_id) REFERENCES employees(id);

-- Slowly-changing-dimension table: every team/role/shift change, ever.
-- employees.current_* is the fast-lookup snapshot; this is the audit trail
-- that answers "what was true on date X" — see the team-move discussion.
CREATE TABLE employee_history (
    id              SERIAL PRIMARY KEY,
    employee_id     TEXT NOT NULL REFERENCES employees(id),
    team_id         INTEGER REFERENCES teams(id),
    role            TEXT,
    shift           TEXT,
    effective_from  DATE NOT NULL,
    effective_to    DATE,                  -- NULL = currently active
    detected_via    TEXT NOT NULL DEFAULT 'daily_sync'  -- 'daily_sync' | 'manual_correction'
);

CREATE INDEX idx_employee_history_employee ON employee_history (employee_id, effective_from);

CREATE TABLE shift_templates (
    id              SERIAL PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,   -- 'day' | 'night' | 'hybrid'
    expected_start  TIME NOT NULL,
    expected_end    TIME NOT NULL,          -- may be earlier than start (crosses midnight)
    grace_minutes   INTEGER NOT NULL DEFAULT 15
);

-- Seed rough windows from what's been discussed. Adjust once confirmed.
INSERT INTO shift_templates (name, expected_start, expected_end, grace_minutes) VALUES
    ('day',    '08:00', '17:00', 15),
    ('night',  '18:00', '02:00', 15),
    ('hybrid', '14:00', '20:00', 60);  -- wider window on purpose — see hybrid discussion

CREATE TABLE attendance_records (
    id              SERIAL PRIMARY KEY,
    employee_id     TEXT NOT NULL REFERENCES employees(id),
    date            DATE NOT NULL,          -- shift START date, even if it crosses midnight
    check_in        TIME,
    check_out       TIME,
    work_hours      NUMERIC(5,2) NOT NULL DEFAULT 0,
    overtime_hours  NUMERIC(5,2) NOT NULL DEFAULT 0,
    late_in         BOOLEAN NOT NULL DEFAULT FALSE,
    early_out       BOOLEAN NOT NULL DEFAULT FALSE,
    present         BOOLEAN NOT NULL DEFAULT FALSE,

    -- snapshot fields: whatever was true ON THIS DATE (from the source
    -- payload for that day), never joined live to employees' current state.
    team_id         INTEGER REFERENCES teams(id),
    assigned_shift  TEXT,                   -- employee's expected shift that day
    matched_shift   TEXT,                   -- which shift_template this punch actually fits
    shift_anomaly   BOOLEAN NOT NULL DEFAULT FALSE,  -- flag for review, never a rejection

    source          TEXT NOT NULL DEFAULT 'migrated',  -- 'biometric' | 'zoho_manual' | 'migrated'
    raw_ref         TEXT,                   -- pointer back to the original log id, once available

    UNIQUE (employee_id, date)
);

CREATE INDEX idx_attendance_employee_date ON attendance_records (employee_id, date);
CREATE INDEX idx_attendance_team_date ON attendance_records (team_id, date);

-- Leave, separated from attendance per the earlier design discussion —
-- distinct status lifecycle (approved/pending), not a per-day attribute.
CREATE TABLE leave_records (
    id          SERIAL PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(id),
    date        DATE NOT NULL,
    leave_type  TEXT NOT NULL,          -- 'Annual Leave', 'Sick Leave', etc.
    status      TEXT NOT NULL DEFAULT 'approved',
    source      TEXT NOT NULL DEFAULT 'zoho',
    UNIQUE (employee_id, date, leave_type)
);

CREATE INDEX idx_leave_employee_date ON leave_records (employee_id, date);

-- Public holidays / non-working days, from Zoho. Weekends are computed
-- from the date itself, not stored — no table needed for those.
CREATE TABLE holidays (
    id      SERIAL PRIMARY KEY,
    date    DATE UNIQUE NOT NULL,
    name    TEXT NOT NULL,
    source  TEXT NOT NULL DEFAULT 'zoho'
);

CREATE TABLE sync_log (
    id                  SERIAL PRIMARY KEY,
    source              TEXT NOT NULL,   -- 'json_migration' | 'zoho_employees' | 'zoho_leave' | 'zoho_holidays' | 'biometric_import'
    run_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    records_processed   INTEGER NOT NULL DEFAULT 0,
    records_failed       INTEGER NOT NULL DEFAULT 0,
    status               TEXT NOT NULL DEFAULT 'complete',  -- 'complete' | 'partial' | 'failed'
    notes                TEXT
);

-- Who's allowed into the DASHBOARD APP — distinct from `employees`, who are
-- the SUBJECTS of attendance. An admin/manager may or may not also be an
-- employee tracked in the system; this table is the access whitelist.
-- Auth: local email/password (argon2id) + Microsoft Entra SSO. Our own
-- HS256 JWT for both; downstream code never sees Entra tokens.
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               TEXT UNIQUE NOT NULL,   -- stored lowercase
    display_name        TEXT,
    role                TEXT NOT NULL DEFAULT 'viewer'
                        CHECK (role IN ('admin', 'manager', 'viewer')),
    auth_provider       TEXT NOT NULL DEFAULT 'local'
                        CHECK (auth_provider IN ('local', 'entra')),
    password_hash       TEXT,                   -- local only
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
CREATE INDEX idx_users_email ON users (email);
CREATE INDEX idx_users_entra_oid ON users (entra_oid);

-- Refresh-token families: opaque token stored as SHA-256 hash, 7-day
-- sliding / 30-day absolute cap, rotated on every use.
CREATE TABLE refresh_tokens (
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
CREATE INDEX idx_refresh_family ON refresh_tokens (family_id);
CREATE INDEX idx_refresh_user ON refresh_tokens (user_id);
CREATE INDEX idx_refresh_hash ON refresh_tokens (token_hash);

-- Auth audit trail. Never stores passwords or token hashes.
CREATE TABLE auth_events (
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
CREATE INDEX idx_auth_events_at ON auth_events (at DESC);

CREATE TABLE audit_log (
    id                  SERIAL PRIMARY KEY,
    actor_user_id       UUID REFERENCES users(id),
    target_employee_id  TEXT REFERENCES employees(id),
    action              TEXT NOT NULL,   -- 'manual_override' | 'role_change' | ...
    before_value         JSONB,
    after_value          JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- WFH approvals: team-lead manual override for approved work-from-home
-- Not reported via Zoho/biometric. Counts as present for attendance rate.
CREATE TABLE wfh_approvals (
    id              SERIAL PRIMARY KEY,
    employee_id     TEXT NOT NULL REFERENCES employees(id),
    date            DATE NOT NULL,
    approved_by     UUID REFERENCES users(id),
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (employee_id, date)
);
CREATE INDEX idx_wfh_employee_date ON wfh_approvals (employee_id, date);
CREATE INDEX idx_wfh_date ON wfh_approvals (date);

-- Leave ingestion (manual Zoho report upload). Mirrors
-- db/migrations/007_leave_ingestion.sql — keep the two in sync.
-- calendar_day.employee_id deliberately has no FK to employees: rows for
-- IDs not yet in the directory are stored and apply when they appear.
CREATE TABLE leave_import (
    id                  SERIAL PRIMARY KEY,
    file_sha256         TEXT NOT NULL,
    original_filename   TEXT NOT NULL,
    uploaded_by         UUID REFERENCES users(id) ON DELETE SET NULL,
    uploaded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    status              TEXT NOT NULL DEFAULT 'parsing'
        CHECK (status IN ('parsing','preview_ready','committing','committed',
                          'failed','discarded','expired','reverted')),
    period_start        DATE,
    period_end          DATE,
    coverage_through    DATE,
    department_label    TEXT,
    sheet_summary       JSONB NOT NULL DEFAULT '[]',
    counts              JSONB NOT NULL DEFAULT '{}',
    preview_names       JSONB,                  -- in-flight preview only, purged after
    base_version        INTEGER NOT NULL DEFAULT 0,
    idempotency_key     TEXT,                   -- client-supplied commit retry key
    error_id            TEXT,
    committed_at        TIMESTAMPTZ,
    reverted_at         TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ,
    recompute_status    TEXT NOT NULL DEFAULT 'pending'
        CHECK (recompute_status IN ('pending','done','failed'))
);

CREATE TABLE leave_import_staging (
    import_id       INTEGER NOT NULL REFERENCES leave_import(id) ON DELETE CASCADE,
    sheet           TEXT NOT NULL,
    employee_id     TEXT NOT NULL,
    date            DATE NOT NULL,
    raw_code        TEXT NOT NULL,
    kind            TEXT NOT NULL
        CHECK (kind IN ('working','weekend','holiday','not_employed',
                        'leave','on_duty','unknown')),
    leave_code      TEXT,
    fraction        NUMERIC(3,2) NOT NULL DEFAULT 1.0,
    zoho_presence   BOOLEAN,
    provisional     BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (import_id, employee_id, date)
);
CREATE INDEX idx_leave_staging_import ON leave_import_staging (import_id);

CREATE TABLE leave_import_issue (
    id              SERIAL PRIMARY KEY,
    import_id       INTEGER NOT NULL REFERENCES leave_import(id) ON DELETE CASCADE,
    severity        TEXT NOT NULL CHECK (severity IN ('error','warning','info')),
    code            TEXT NOT NULL,
    sheet           TEXT,
    row             INTEGER,
    col             INTEGER,
    employee_id     TEXT,
    date            DATE,
    occurrences     INTEGER NOT NULL DEFAULT 1,
    message         TEXT NOT NULL,
    samples         JSONB
);
CREATE INDEX idx_leave_issue_import ON leave_import_issue (import_id);

CREATE TABLE leave_code_map (
    code                TEXT PRIMARY KEY,
    label               TEXT NOT NULL,
    kind                TEXT NOT NULL
        CHECK (kind IN ('working','weekend','holiday','not_employed',
                        'leave','on_duty','unknown')),
    leave_group         TEXT,
    paid                BOOLEAN,
    counts_as_present   BOOLEAN NOT NULL DEFAULT FALSE,
    aliases             TEXT[] NOT NULL DEFAULT '{}',
    sensitive           BOOLEAN NOT NULL DEFAULT FALSE,
    active              BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO leave_code_map
    (code, label, kind, leave_group, paid, counts_as_present, aliases, sensitive, active)
VALUES
    ('P',  'Present (Zoho)',        'working',      NULL,       NULL,  FALSE, '{}', FALSE, TRUE),
    ('A',  'Absent (Zoho)',         'working',      NULL,       NULL,  FALSE, '{}', FALSE, TRUE),
    ('W',  'Weekend',               'weekend',      NULL,       NULL,  FALSE, '{}', FALSE, TRUE),
    ('H',  'Holiday',               'holiday',      NULL,       NULL,  FALSE, '{}', FALSE, TRUE),
    ('-',  'Not employed',          'not_employed', NULL,       NULL,  FALSE, '{}', FALSE, TRUE),
    ('EL', 'Annual Leave',          'leave',        'annual',   TRUE,  FALSE, '{ANNUAL,ANNUAL_LEAVE}',          FALSE, TRUE),
    ('SL', 'Sick Leave',            'leave',        'sick',     TRUE,  FALSE, '{SICK,SICK_LEAVE}',              TRUE,  TRUE),
    ('ML', 'Maternity Leave',       'leave',        'maternity',TRUE,  FALSE, '{MATERNITY,MATERNITY_LEAVE}',    TRUE,  TRUE),
    ('PL', 'Paternity Leave',       'leave',        'paternity',TRUE,  FALSE, '{PATERNITY,PATERNITY_LEAVE}',    TRUE,  TRUE),
    ('L',  'Unpaid Leave',          'leave',        'unpaid',   FALSE, FALSE, '{UNPAID,UNPAID_LEAVE}',          FALSE, TRUE),
    ('OD', 'On Duty',               'on_duty',      NULL,       NULL,  TRUE,  '{ON_DUTY,ONDUTY}',               FALSE, TRUE),
    ('SL1','Sick Leave (USA)',      'leave',        'sick',     TRUE,  FALSE, '{}', TRUE,  TRUE),
    ('AL', 'Annual Leave (SA)',     'leave',        'annual',   TRUE,  FALSE, '{}', FALSE, TRUE)
ON CONFLICT (code) DO NOTHING;

CREATE TABLE calendar_day (
    employee_id     TEXT NOT NULL,
    date            DATE NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('xls','api')),
    raw_code        TEXT NOT NULL,
    kind            TEXT NOT NULL
        CHECK (kind IN ('working','weekend','holiday','not_employed',
                        'leave','on_duty','unknown')),
    leave_code      TEXT,
    fraction        NUMERIC(3,2) NOT NULL DEFAULT 1.0,
    zoho_presence   BOOLEAN,
    batch_id        INTEGER REFERENCES leave_import(id),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (employee_id, date, source)
);
CREATE INDEX idx_calendar_day_date ON calendar_day (date);

CREATE TABLE calendar_day_change (
    id              BIGSERIAL PRIMARY KEY,
    batch_id        INTEGER NOT NULL REFERENCES leave_import(id),
    employee_id     TEXT NOT NULL,
    date            DATE NOT NULL,
    source          TEXT NOT NULL,
    old_raw         TEXT,
    new_raw         TEXT NOT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_calendar_change_batch ON calendar_day_change (batch_id);

CREATE TABLE leave_coverage (
    source          TEXT PRIMARY KEY CHECK (source IN ('xls','api')),
    through_date    DATE NOT NULL,
    batch_id        INTEGER REFERENCES leave_import(id),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A committed (or live preview) file is a no-op on re-upload; failed,
-- discarded, expired or reverted files may be re-uploaded fresh.
CREATE UNIQUE INDEX uq_leave_import_sha_live ON leave_import (file_sha256)
    WHERE status IN ('parsing', 'preview_ready', 'committing', 'committed');
-- A commit idempotency key replays to the same import, never a duplicate.
CREATE UNIQUE INDEX uq_leave_import_idem ON leave_import (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
