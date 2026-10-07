-- COSEC attendance ingestion raw tables (see api/app/ingestion/).
-- Apply to an existing DB: psql $DATABASE_URL -f db/migrations/003_cosec_ingestion.sql
-- Fresh `docker compose up` volumes also pick this up via init.sql include.
-- IF NOT EXISTS guards make re-apply safe (same style as 002).
CREATE TABLE IF NOT EXISTS cosec_users (
    user_id       text PRIMARY KEY,
    user_name     text NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    in_scope      boolean NOT NULL DEFAULT false,
    team          text NULL
);

CREATE TABLE IF NOT EXISTS cosec_attendance_daily (
    user_id           text NOT NULL REFERENCES cosec_users(user_id),
    process_date      date NOT NULL,
    punch1            timestamptz NULL,
    punch2            timestamptz NULL,
    working_shift     text NULL,
    late_in_min       integer NULL,
    early_out_min     integer NULL,
    overtime_min      integer NULL,
    work_time_min     integer NULL,
    is_processed      boolean NOT NULL,
    quality           text NOT NULL
        CHECK (quality IN ('ok','no_punch','open','mismatch','long_span','anomaly')),
    first_ingested_at timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, process_date)
);

CREATE INDEX IF NOT EXISTS cosec_attendance_daily_process_date_idx
    ON cosec_attendance_daily (process_date);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id             bigserial PRIMARY KEY,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz NULL,
    mode           text NOT NULL CHECK (mode IN ('backfill','poll')),
    range_from     date NOT NULL,
    range_to       date NOT NULL,
    status         text NOT NULL CHECK (status IN ('running','success','failed')),
    rows_received  integer NULL,
    rows_written   integer NULL,
    rows_malformed integer NULL,
    error          text NULL
);
