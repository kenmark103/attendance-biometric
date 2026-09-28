-- Apply if DB already initialized before this commit:
-- psql $DATABASE_URL -f db/migrations/002_wfh_approvals.sql
CREATE TABLE IF NOT EXISTS wfh_approvals (
    id              SERIAL PRIMARY KEY,
    employee_id     TEXT NOT NULL REFERENCES employees(id),
    date            DATE NOT NULL,
    approved_by     INTEGER REFERENCES app_users(id),
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (employee_id, date)
);
CREATE INDEX IF NOT EXISTS idx_wfh_employee_date ON wfh_approvals (employee_id, date);
CREATE INDEX IF NOT EXISTS idx_wfh_date ON wfh_approvals (date);
