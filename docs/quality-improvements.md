# Quality improvements

This document records the maintenance work applied during the quality review.
Changes are intentionally incremental and preserve existing routes and data
contracts.

## Applied

### 1. Removed experimental secret extractor

`api/app/routers/secret_extractor.py` was untracked, executed external requests
at import time, contained hard-coded document URLs, and required an undeclared
dependency. It has been removed from the working tree and is not part of the
application.

### 2. Fixed manual-ingestion engine lifetime

`POST /ingestion/sync-now` now reuses one SQLAlchemy engine for polling and
promotion and disposes it in a `finally` block. The promotion cursor is also
closed if execution fails. This prevents avoidable connection-pool/resource
leaks without changing the endpoint response.

### 3. Added structured logging for startup and sync warnings

The startup leave-janitor warning and ingestion scope-restoration warning now
use Python logging instead of `print()`. CLI tools still use `print()` where
their output is intentionally user-facing.

### 4. Added a database readiness endpoint

`GET /ready` performs a lightweight `SELECT 1` and returns HTTP 503 when the
API cannot reach PostgreSQL. `/health` remains a lightweight process/liveness
check.

### 5. Added classification regression tests

The metrics tests now explicitly cover the ordering between non-working,
pending, absent, and unverified dates, plus the rule that a punch wins over
leave while recording a leave conflict. These tests run without PostgreSQL.

### 6. Added database-aware Docker readiness

The API container healthcheck now calls `/ready` instead of `/health`, so
dependent services wait for database readiness rather than only process
liveness.

### 7. Improved operational logging

Leave preview, commit, discard, revert, and reprocess messages now use the
backend logger with structured arguments instead of direct `print()` calls.

### 8. Added dashboard route-level code splitting

The dashboard bundle is now lazy-loaded with React `Suspense`, reducing the
initial application bundle while preserving the existing route and props.

### 9. Added COSEC promotion regression coverage

`tests/ingestion/test_promotion.py` covers the staging-to-dashboard boundary:
scope filtering, team/employee creation, minute-to-hour conversion, timezone
preservation, biometric row updates, and protection of migrated rows. It uses
the existing `db` pytest marker and requires the compose PostgreSQL instance.

### 10. Cancelled stale dashboard metric requests

Dashboard metric requests now use `AbortController`. Changing filters cancels
the previous request, preventing stale responses from racing with the current
view and avoiding unnecessary server/browser work.

### 11. Standardized promoter-worker logging

The long-running promotion worker now uses Python logging with timestamps,
levels, and a configurable `LOG_LEVEL`. Its Docker-visible messages and retry
behavior remain intact; one-off CLI tools still use direct output deliberately.

### 12. Completed attendance-router logging cleanup

The bulk attendance team-update path now uses the backend logger for lookup
diagnostics and missing-team warnings instead of direct `print()` calls.

### 13. Added repeatable CI verification

The repository now has a GitHub Actions workflow that runs frontend tests and
builds, backend pure tests, and database-backed tests against PostgreSQL 16.
The frontend also exposes `npm test` for the existing Node test suite.

### 14. Reduced dashboard and router responsibilities

Read-only attendance and coverage endpoints now live in
`api/app/routers/attendance_reads.py`, while bulk writes remain in
`api/app/routers/attendance.py`. The dashboard metrics request lifecycle,
including filter-key calculation and abort handling, now lives in
`frontend/src/hooks/useDashboardMetrics.js`.

### 15. Added request-level transaction cleanup

The shared database dependency now rolls back an uncommitted transaction when
an endpoint raises, then closes the request-scoped connection as before. This
protects bulk writes from leaving failed transaction state behind while
preserving the existing explicit commits on successful writes.

### 16. Standardized operational logging and frontend API errors

Remaining leave-import and janitor server messages now use Python logging with
levels and structured fields instead of direct `print()` calls. The frontend
API layer now extracts backend `detail` values into one error format and
attaches the HTTP status to the thrown error, without changing response
payloads or status codes.

### 17. Reconnected backend day statuses to legacy frontend views

The dashboard metrics payload already included per-day statuses and flags, but
the frontend classifier recomputed legacy-mode statuses. The display path now
consumes those backend statuses when leave-calendar overlay mode is inactive;
the richer overlay classifier remains for leave-specific states such as half
leave and worked-on-leave conflicts.

### 18. Moved bulk-write transactions into an attendance service

The attendance router now handles only authorization, source validation, and
delegation. Attendance, leave, and team-update SQL—including cursor cleanup,
commit, and rollback behavior—now lives in
`api/app/attendance/service.py`. The public routes and response shapes are
unchanged.

### 19. Added explicit response contracts and schema validation

Bulk attendance/leave/team-update responses and health/readiness responses now
have Pydantic response models. CI also validates the minimum runtime database
tables and columns after initializing PostgreSQL, catching incomplete schema
provisioning before database tests run.

### 20. Extracted dashboard shell components

The dashboard header and tab navigation now live in
`frontend/src/components/DashboardChrome.jsx`. Routing, filters, data loading,
and view scope remain in `Dashboard.jsx`, reducing its presentation
responsibility without changing navigation behavior.

## Remaining backlog

- Standardizing psycopg2 versus SQLAlchemy.
- Adding a backend-wide error envelope while preserving existing clients.
- Dependency/security upgrade policy.

These are intentionally deferred because they touch more behavior and should
be implemented with focused tests and small diffs.

## Three-phase status

### Phase 1 — safety and verification: complete

Readiness, logging improvements, classification regression tests, COSEC
promotion coverage, frontend tests, production builds, and CI coverage are in
place.

### Phase 2 — maintainability: in progress

Read-only attendance and coverage endpoints now live in
`api/app/routers/attendance_reads.py`; bulk write endpoints remain in
`attendance.py`. Public routes and response shapes are unchanged. The
metrics request lifecycle now lives in
`frontend/src/hooks/useDashboardMetrics.js`, reducing the responsibility of
`Dashboard.jsx` without changing its props or route behavior.

### Phase 3 — consistency and operations: in progress

CI is now defined. Remaining work includes migration validation and
dependency/security checks. The schema validator now covers the fresh-database
runtime contract; migration-history validation and the React Router major
upgrade remain deliberate follow-up work.

The local dependency scan found two moderate `react-router` advisories in the
current 6.30.6 line. The available audit fix requires a React Router v7 major
upgrade, so it was not applied automatically; the compatibility migration is
now an explicit release task rather than an unverified forced upgrade.
