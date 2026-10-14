-- 006_sync_state: poller health for the Data health tab.
-- The supervisor loop (cable-pull resilient) records healthy / degraded /
-- down / auth_blocked here on every state change, so the dashboard can show
-- whether the device link is alive without reading container logs.
-- Apply: psql $DATABASE_URL -f db/migrations/006_sync_state.sql

CREATE TABLE IF NOT EXISTS sync_state (
    service     TEXT PRIMARY KEY,
    state       TEXT NOT NULL,   -- healthy | degraded | down | auth_blocked
    since       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
