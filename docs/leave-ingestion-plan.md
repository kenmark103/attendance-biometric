# Leave Ingestion — Implementation Plan

Spec: `Leave Ingestion Implementation Spec for OpenCode` v1 (15 Oct 2026).
Repo conventions used below were read from the tree on 16 Oct 2026
(`api/app`, `db/init.sql` + `db/migrations/00N_*.sql`, `scripts/`,
`frontend/src`, `pytest` + `node --test`).

> **Approval gate:** nothing in §1–§8 is implemented until this plan is
> approved. Step 0 (PII safety) may land first on request since it is
> independent and urgent.

## Step 0 — PII safety (do first, ~10 min)

- Add to `.gitignore`: `*.xls`, `*.xlsx`, `/data/.leave_uploads/`
  (spec §0 hard rule; currently `data/Engineering.xls` sits untracked
  and committable — must never be committed).
- No code changes. Verify with `git status` / `git check-ignore`.

## AGENT DECIDES resolutions (fixed for the whole build)

| # | Spec item | Choice in this repo | Rationale |
|---|-----------|---------------------|-----------|
| 1 | ORM / migrations | No ORM. Raw psycopg2 SQL, matching `api/app`. New `db/migrations/007_leave_ingestion.sql` (`IF NOT EXISTS`, same style as 002–006) **plus** the same DDL appended to `db/init.sql` (fresh-DB path). Existing DBs apply via `psql $DATABASE_URL -f …` per README pattern | Repo has no migration runner; 002–006 are manual psql |
| 2 | Table / route names | Tables exactly as spec §4 (`leave_import`, `leave_import_staging`, `leave_import_issue`, `leave_code_map`, `calendar_day`, `calendar_day_change`, `leave_coverage`). New router `api/app/routers/leave_import.py`, prefix `/leave`, wired in `main.py` next to existing routers. Existing `GET /leave` (leave_records) untouched | Spec names are already repo-compatible; no collision (`/leave/imports`, `/leave/coverage`, `/leave/types`, `/leave/template-sample`) |
| 3 | Background mechanism | **Documented deviation:** parse runs **synchronously inside `POST /leave/imports`** (file ≤10 MB, ~48k cells, parses in seconds). All status/polling endpoints from spec §7 are still implemented, so a worker thread/process can be dropped in later without API change | Repo has no job infra (endpoints are sync; loops live in separate containers). Adding Celery/threads for a <5 s parse is unjustified complexity; crash-mid-parse just fails the request, nothing is stored yet |
| 4 | Attendance recompute location | No server-side batch recompute needed: this repo computes day status **client-side** in `frontend/src/metrics.js` from API rows. "Recompute" = new calendar rows are immediately served by the API + `base_version` bump invalidates open previews. `recompute_status` still tracked (set `done` after verification queries pass) | There is no server-side daily-status table to refresh; promotion SQL (`promote_cosec_to_attendance.sql`) is insert-only-new and unrelated |
| 5 | Daily JSON export | `fetchDayRecords` in `frontend/src/api.js` merges the new calendar rows; `metrics.js` `classifyDay` implements spec §9 table. Server adds `GET /leave/calendar?date_from&date_to` (flat rows: `day_kind`, `leave_type` role-gated, `leave_fraction`, `zoho_presence`) | Follows the existing attendance→leave→holiday→wfh merge shape |
| 6 | Role model | `users.role ∈ (admin, manager, viewer)`; all write + preview endpoints `Depends(admin)` (same as `/attendance/bulk`); leave-type detail visible to admin only (`LEAVE_TYPE_DETAIL_ROLES`, default `admin`), others get `"On leave"` | Spec D12; existing `deps.admin` / `viewer` |
| 7 | Biometric sync watermark | A date has biometric coverage iff it appears in `/stats/coverage` `per_date` with `count > 0` (promoted `attendance_records`) — i.e. the existing coverage endpoint **is** the watermark; `sync_state` (006) stays the device-link signal | No new watermark table; cable-pull work (d596817) already owns link health |
| 8 | Active employees | `employees.status = 'active'` (existing column); inactive excluded by existing logic, untouched | Spec §9 carry-forward |
| 9 | Temp file location | `/data/.leave_uploads/` (the `./data` volume is already mounted into `api`; private, non-repo, gitignored). Swept by janitor (24 h expiry) | Spec §12; matches `SCOPE_CSV_PATH=/data/…` precedent |
| 10 | UI library / router | React 18 + react-router v6, inline-style views (no component kit in repo). New `frontend/src/views/LeaveImport.jsx`, route `/leave`, admin-gated exactly like `/users`; "Leave data" tab in `Dashboard.jsx` `TABS` for admins | Follows `UsersPage` gating precedent |
| 11 | `MIN_PUNCH_MINUTES` | Env `MIN_PUNCH_MINUTES`, **default 0** = any punch counts as present. Preserves current `classifyDay` behaviour; threshold only bites if deliberately raised | No existing threshold to match |
| 12 | Fixture dependencies | `scripts/make_leave_fixture.py` uses `openpyxl` (+ `xlwt` if xls output needed — else xlsx-only plus the HTML-disguised-xls case via stdlib). Test-only; outputs go to `Temp`, never committed | Keeps container requirements (spec: `xlrd` + `openpyxl` in `api/requirements.txt`) minimal |

Config/env additions (all with spec defaults): `TRUST_ZOHO_PRESENCE=true`,
`LEAVE_SOURCE_PRIORITY=api,xls`, `LEAVE_TYPE_DETAIL_ROLES=admin`,
`MIN_PUNCH_MINUTES=0`, `EXPECTED_DEPARTMENT_LABELS` (seeded with
`GBS- ENGINEERING CENTRE,Engineering Centre`), `LEAVE_UPLOAD_MAX_MB=10`.

## Phase 1 — Schema, code map, parser, fixtures (§17.1; spec §§2,4,5,15)

- `db/migrations/007_leave_ingestion.sql` + `db/init.sql` append: 7 tables
  per spec §4 (status/check constraints included), `leave_code_map` seed
  rows for every code in spec §2 table (incl. `SL1`, `AL`, `OD`), Kenyan
  seed holidays as config/display-only (no status effect).
- `api/requirements.txt`: add `xlrd`, `openpyxl`.
- New `api/app/leave/parsing.py`: **pure function** `parse_leave_workbook(bytes)`
  → `(sheets, staging_rows, issues)`; sniff magic bytes (OLE2/ZIP/HTML),
  10 MB guard, header scan (first row in 15 with `Employee Id` in first
  3 cells), Start/End-Date cells, `{d} - {Mon}` validation, ID normalise
  (float-int → str, trim, strip inner spaces, strip leading zeros on match
  key), cell grammar (`[fraction]CODE[/fraction]CODE`, fraction ∈ {0.5,.5}),
  D5 provisional-last-column rule, all §6 code paths. No DB access, no names
  in issues/logs.
- `scripts/make_leave_fixture.py`: synthetic generator with every §15 switch
  (compound/half-day codes, interior dash, unknown code, duplicate rows,
  missing A1, provisional last column, leaver drop-off, HTML `.xls`).
- Tests `api/tests/test_leave_parsing.py`: header scan, dates/headers, ID
  normalisation, grammar, D5, every §6 code, §9 status table (1 case/row +
  half-day + carry-forward). Fixtures synthetic only.
- **Accept:** `pytest` green; real-file invariant counts reproduced locally
  (10 sheets / 181 IDs / 48,536 cells, §2 table) — local-only, never in CI.

## Phase 2 — Staging, diff, preview API (§17.2; spec §§5–7)

- New `api/app/routers/leave_import.py`: `POST /leave/imports` (multipart;
  SHA-256 dup → `already_imported`), `GET /imports/{id}` (status/summary/
  per-sheet), `GET …/issues` (severity/code/sheet filters + pagination),
  `GET …/changes` (new/changed/leave-removed + pagination),
  `GET /leave/imports` (history), `GET /leave/coverage`,
  `GET /leave/template-sample` (synthetic download).
- Staging writes in ~5k chunks; set-based diff vs `calendar_day`
  (new/changed/unchanged + past-day list); `base_version` captured at parse.
- Issues aggregated with occurrence counts + samples, never names.
- **Accept:** upload → preview → issues/changes round-trip covered by
  integration tests on synthetic files; error-copy table (§11) mapped.

## Phase 3 — Commit, audit, coverage, revert, janitor (§17.3; spec §8)

- `POST …/commit {sheets, confirm_large_change, idempotency_key}`:
  `pg_advisory_xact_lock`, state/expiry/`base_version`/idempotency checks
  (409s per §6), **single transaction** (audit → upsert-changed-only →
  coverage → `committed`), staging + temp file purge. D9 5 % guard.
  `POST …/discard`, `POST …/revert` (latest committed only, skip-and-report;
  revert re-derives coverage from remaining calendar rows, which stays exact
  under per-sheet commits).
  Janitor: startup sweep + per-upload sweep (stuck `parsing` >15 min → failed;
  stale `committing` → failed; previews expire 24 h).
- `GET/PUT /leave/types` (admin) + `POST /leave/reprocess` (map change →
  kind recompute from `raw_code`).
- **Accept:** integration tests — re-upload no-op, corrected-month,
  cancellation (`LEAVE_REMOVED`), revert, stale-preview 409,
  concurrent-commit 409, janitor transitions.

## Phase 4 — Status overlay + export (§17.4; spec §9)

- `frontend/src/api.js`: merge `GET /leave/calendar` rows into day records
  (`day_kind`, `leave_type` role-gated server-side, `leave_fraction`,
  `status`, `present_source`, `verified`).
- `frontend/src/metrics.js`: `classifyDay` extended to the 9-row §9 table
  (`not_employed`, `worked_holiday/weekend`, `on_duty`, `leave_conflict`,
  `half_leave`, `present_zoho_only` behind `TRUST_ZOHO_PRESENCE`,
  `absent` only on biometrically-covered dates else `absent_unverified`,
  `unverified`, carry-forward rule). Denominator/metric updates + both
  calendar-day and working-day leave counts.
- Extend `frontend/tests/attendance-metrics.test.js` (`node --test`).
- **Accept:** one test case per §9 row + half-day + carry-forward +
  outage (`absent_unverified`) cases; dashboard numbers unchanged when no
  calendar data exists (backwards compatible).

## Phase 5 — Upload / preview / history UI (§17.5; spec §11)

- `views/LeaveImport.jsx`: coverage banner (amber >10 days stale), drag-drop
  upload + sample download, progress polling (1 s → 5 s backoff, reload
  resume), summary cards, per-sheet table (checkboxes, blocked-sheet reasons),
  Issues / Changes / Unmatched / Conflicts tabs (CSV export, no names),
  commit modal + D9 checkbox + idempotency lock, result + history (revert
  latest-only, reprocess, view issues), `leave_code_map` admin editor.
  HTTP-status error copy per §11.
- **Accept:** manual walkthrough of every §11 state incl. blocked sheets,
  large-change confirm, mid-upload network failure.

## Phase 6 — Dashboard + data-quality panel (§17.6; spec §11)

- Status legend/colours for §9 statuses, coverage banner + `unverified`
  markers, admin-only leave-type filter (`On leave` for others),
  employee drill-down badges (`worked on leave day`, `Zoho only`),
  data-quality panel (leave conflicts, unverified days, no-leave-data
  employees, Zoho-vs-biometric disagreements).
- `LeaveBanner` ("not loaded from Zoho") retires once coverage exists.
- **Accept:** visual review + frontend tests for new states.

## Phase 7 — Local backfill + reconciliation (§17.7; spec §10)

Local-only (never CI, never committed): upload real report in staging/local,
expect 10 sheets / 181 IDs / 48,389 rows after D5 (15-Oct excluded:
P −72, `-` −65, EL −5, SL −3, ML −2); commit; recompute 1 Jan–14 Oct;
spot-check vs Zoho UI. New `scripts/leave_reconcile.py` (output to `Temp`):
Zoho-A-vs-biometric-present, Zoho-P-vs-no-punch, leave-days-with-punches.
**Accept:** smoke totals match; reconciliation report delivered.

## Phase 8 — Hardening (§17.8)

Advisory-lock contention test, log/PII audit (ids + counts + codes only),
error-copy pass, README update (migration apply line + env table), PR
description stating every AGENT DECIDES choice.

## Explicitly out of scope (per spec)

Leave balances/approvals/in-app editing, other departments, Zoho API client
(seam only: `LeaveSource.fetch(period)` interface + `XlsSource`; §14),
`public_holiday_seed` beyond display-only.

## PENDING-HR defaults (ship as data/config, §16)

`EL/P` = leave conflict; `L` = Unpaid Leave; `OD` = On Duty (present);
no emergency/compassionate code (→ `unknown`); no Paid-Leave code (→ none);
Sat/Sun `H` = holiday. All live in `leave_code_map`/config so HR answers
change data, not code.
