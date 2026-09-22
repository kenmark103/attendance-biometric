# Phase 3 Plan — Zoho + Biometric Ingestion

Status: Phase 2 done (Vite frontend on 3001 talks to API on 8001). Phase 3 builds the write side. Currently there are **schema stubs only** — no service logic.

## 1. What exists today vs what is actually stubbed

| Area | Exists now | Stub / Missing |
|---|---|---|
| `db/init.sql:25` `employee_history` | DDL + index | Never written — no Zoho change detection |
| `db/init.sql:38` `shift_templates` | Seeded day/night/hybrid windows | No matching — `attendance_records.matched_shift/shift_anomaly` stay NULL `db/init.sql:67` |
| `db/init.sql:96` `holidays` | DDL, empty | No Zoho holiday fetch; `GET /holidays` `api/app/main.py:171` returns `[]` |
| `db/init.sql:103` `sync_log` | DDL with `partial/failed` | Only loader writes `json_migration`; no `zoho_*` / `biometric_import` rows |
| `api/app/main.py:171` `audit_log` | DDL | Never written (read-only, correct per your decision) |
| Zoho OAuth / API client | Nothing | Awaiting org service account + `api-console.zoho.com` credentials |
| Biometric client | Nothing | Awaiting endpoint format + lab-network routing |
| Scheduled jobs | Nothing | No timer / Azure Function / cron |

So Phase 3 is **not partially implemented** — it is **DDL + read API awaiting ingestion code**. The fetch order is documented in `README.md:77` but not enforced by code yet beyond FK `attendance_records.employee_id` `db/init.sql:54`.

## 2. Prerequisites (blocking)

* **Zoho:** org-owned service account (not personal), OAuth app in `api-console.zoho.com`, refresh token storage (Key Vault in prod, `.env` for local), API rate limit tier, whether `modified_since` is supported for incremental sync, and whether historic logging defect has a known date range.
* **Biometric:** device HTTP endpoint + payload shape (punch list vs aggregated day rows), clock NTP sync, and network path from your corp machine / from Azure.
* **Shift truth:** confirm `Resource List` Shift values (Day/Night) and `shift_templates:47` windows — hybrid currently `14:00-20:00 grace 60`.

## 3. Build order (FK + trust, same order every sync)

Per `README.md:79`: **1) Zoho employees/teams → 2) Zoho leave/holidays → 3) biometric → 4) reconcile**. Reconciliation trust: biometric wins presence, Zoho wins leave/exemption.

### 3.1 Zoho auth module `sync/zoho_auth.py` (new)

* Exchange `ZOHO_REFRESH_TOKEN` (from `.env.example` → Key Vault later) for 1h access token per run; alert on invalidation.
* Local dev: single nightly pull `?date=previous day` via polling (~03:00) — not webhooks (Zoho People has no reliable punch push). Store watermark in `sync_log:103`.

### 3.2 Employees/teams `sync/zoho_employees.py`

* `GET /people/employees` → upsert `teams` by name (trim `App Compat `), then `employees(id,name,current_team_id,"current_role","current_shift",status)`. `status` handles offboarding soft-delete (never hard-delete, `db/init.sql:17`).
* Detect changes vs `employees` snapshot → insert `employee_history:25` (`effective_from`/`effective_to`, `detected_via`).
* Write `sync_log source='zoho_employees'`.

### 3.3 Leave & holidays `sync/zoho_leave.py`, `sync/zoho_holidays.py`

* Leave → `leave_records:82` `(employee_id,date,leave_type)` — separate lifecycle, not per-day attribute.
* Holidays → `holidays:96` (weekends computed client-side, not stored). Write `sync_log`.

### 3.4 Biometric `sync/biometric.py`

* Fetch raw punches, aggregate `first_in/last_out` per employee/day if multiple taps, map night-shift crossing midnight to **start date** `db/init.sql:55`, handle missing checkout cutoff (flag `incomplete`, never guess `work_hours`).
* Upsert `attendance_records:52` (`source='biometric'`, `raw_ref` pointer), match against `shift_templates:38` to fill `matched_shift`/`shift_anomaly` (anomaly = flag, not rejection).
* Write `sync_log source='biometric_import'` with `status partial` if run dies mid-day — dashboard flags it.

### 3.5 Reconcile `sync/reconcile.py` (scheduled after 3.1-3.4)

* Diff day/employee where both sources present: flag `leave says absent / biometric says present` for review, never silently overwrite. Produce discrepancy report before prod writes (migration §5 of blueprint).

## 4. Service shape

* Local: `sync/` as Python package + `docker-compose --profile tools run --rm sync` or cron container. Prod: Azure Function timer (NCRONTAB) — same code, different trigger.
* No new tables; add `sync/config` for watermark if needed, otherwise reuse `sync_log`.
* `frontend/src/api.js:7` unchanged — it already merges `attendance` + `leave`; it will just see richer data once holidays/employee_history populate.

## 5. Acceptance

* After Zoho creds: `sync_log` shows `zoho_employees/zoho_leave/zoho_holidays` daily, `employee_history` grows on team/role changes, `holidays` non-empty.
* After biometric: `attendance_records.source` includes `biometric` rows, `shift_anomaly` populated, partial sync shows warning in dashboard instead of fake zeros.

## 6. Not in Phase 3

* Entra ID flip (`AUTH_REQUIRED=true`), `audit_log` writes, Azure deploy hardening — Phase 4.
