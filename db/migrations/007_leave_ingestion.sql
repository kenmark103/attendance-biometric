-- 007_leave_ingestion: manual Zoho leave-report ingestion (calendar overlay).
-- Spec: Leave Ingestion Implementation Spec for OpenCode v1, §§4–8.
-- Apply if DB already initialized before this commit:
-- psql $DATABASE_URL -f db/migrations/007_leave_ingestion.sql
-- Fresh `docker compose up` volumes pick this up via db/init.sql instead.
-- IF NOT EXISTS / DO NOTHING guards make re-apply safe (same style as 002).
--
-- Design notes:
-- - calendar_day.employee_id has NO foreign key to employees: rows for IDs
--   not yet in the directory are still stored (EMPLOYEE_NOT_IN_SYSTEM) and
--   apply when the employee appears.
-- - calendar_day_change is append-only by convention (revert + history read
--   it; nothing updates or deletes it).
-- - leave_import.base_version = COALESCE(MAX(id)) of committed imports at
--   preview time; a commit whose base_version is stale gets 409.
-- - No public_holiday_seed table: the existing `holidays` table already owns
--   global holidays (empty until the Zoho sync exists); per-employee H codes
--   come through calendar_day.

CREATE TABLE IF NOT EXISTS leave_import (
    id                  SERIAL PRIMARY KEY,
    file_sha256         TEXT NOT NULL UNIQUE,   -- same bytes twice => no-op
    original_filename   TEXT NOT NULL,
    uploaded_by         UUID REFERENCES users(id) ON DELETE SET NULL,
    uploaded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    status              TEXT NOT NULL DEFAULT 'parsing'
        CHECK (status IN ('parsing','preview_ready','committing','committed',
                          'failed','discarded','expired','reverted')),
    period_start        DATE,
    period_end          DATE,
    coverage_through    DATE,                   -- last non-provisional date
    department_label    TEXT,
    sheet_summary       JSONB NOT NULL DEFAULT '[]',
    counts              JSONB NOT NULL DEFAULT '{}',
    base_version        INTEGER NOT NULL DEFAULT 0,
    error_id            TEXT,
    committed_at        TIMESTAMPTZ,
    reverted_at         TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ,            -- previews expire after 24h
    recompute_status    TEXT NOT NULL DEFAULT 'pending'
        CHECK (recompute_status IN ('pending','done','failed'))
);

CREATE TABLE IF NOT EXISTS leave_import_staging (
    import_id       INTEGER NOT NULL REFERENCES leave_import(id) ON DELETE CASCADE,
    sheet           TEXT NOT NULL,
    employee_id     TEXT NOT NULL,              -- IDs only, never names
    date            DATE NOT NULL,
    raw_code        TEXT NOT NULL,
    kind            TEXT NOT NULL
        CHECK (kind IN ('working','weekend','holiday','not_employed',
                        'leave','on_duty','unknown')),
    leave_code      TEXT,                       -- FK omitted: reprocess-safe
    fraction        NUMERIC(3,2) NOT NULL DEFAULT 1.0,
    zoho_presence   BOOLEAN,                    -- NULL = not applicable
    provisional     BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (import_id, employee_id, date)
);
CREATE INDEX IF NOT EXISTS idx_leave_staging_import
    ON leave_import_staging (import_id);

CREATE TABLE IF NOT EXISTS leave_import_issue (
    id              SERIAL PRIMARY KEY,
    import_id       INTEGER NOT NULL REFERENCES leave_import(id) ON DELETE CASCADE,
    severity        TEXT NOT NULL CHECK (severity IN ('error','warning','info')),
    code            TEXT NOT NULL,              -- §6 taxonomy, e.g. CELL_WEEKEND_MISMATCH
    sheet           TEXT,
    row             INTEGER,
    col             INTEGER,
    employee_id     TEXT,                       -- IDs only, never names
    date            DATE,
    occurrences     INTEGER NOT NULL DEFAULT 1,
    message         TEXT NOT NULL,
    samples         JSONB                       -- a few sample coords, no PII
);
CREATE INDEX IF NOT EXISTS idx_leave_issue_import
    ON leave_import_issue (import_id);

-- Canonical code map. kind/leave_group derived from raw_code THROUGH this
-- table, so mapping changes + reprocess fix history without re-upload (D2).
-- paid is NULL where HR has not confirmed; sensitive gates type detail (D12).
CREATE TABLE IF NOT EXISTS leave_code_map (
    code                TEXT PRIMARY KEY,       -- base code, e.g. 'EL'
    label               TEXT NOT NULL,
    kind                TEXT NOT NULL
        CHECK (kind IN ('working','weekend','holiday','not_employed',
                        'leave','on_duty','unknown')),
    leave_group         TEXT,                   -- annual | sick | maternity | paternity | unpaid
    paid                BOOLEAN,
    counts_as_present   BOOLEAN NOT NULL DEFAULT FALSE,
    aliases             TEXT[] NOT NULL DEFAULT '{}',  -- future Zoho API type names
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

CREATE TABLE IF NOT EXISTS calendar_day (
    employee_id     TEXT NOT NULL,              -- no FK: unknown IDs stored (see above)
    date            DATE NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('xls','api')),
    raw_code        TEXT NOT NULL,              -- always stored (D2)
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
CREATE INDEX IF NOT EXISTS idx_calendar_day_date ON calendar_day (date);

CREATE TABLE IF NOT EXISTS calendar_day_change (
    id              BIGSERIAL PRIMARY KEY,
    batch_id        INTEGER NOT NULL REFERENCES leave_import(id),
    employee_id     TEXT NOT NULL,
    date            DATE NOT NULL,
    source          TEXT NOT NULL,
    old_raw         TEXT,                       -- NULL = row is new
    new_raw         TEXT NOT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_calendar_change_batch
    ON calendar_day_change (batch_id);

CREATE TABLE IF NOT EXISTS leave_coverage (
    source          TEXT PRIMARY KEY CHECK (source IN ('xls','api')),
    through_date    DATE NOT NULL,
    batch_id        INTEGER REFERENCES leave_import(id),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
