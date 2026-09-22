# Phase 2 Plan — Frontend API Integration & Theme Carry-forward

Status: Phase 1 is done — `db` healthy, `api` on 8001, `auth` on 8002, `frontend` on 3001, loader imported 4356 attendance + 306 leave rows. Roles dropped (flat viewer), `departments` removed, `employee.id` is single source across biometric/Zoho (no `zoho_user_id`), read-only system (no manual overrides — audit_log stays dormant).

## 1. Reference material now organized

* `frontend/reference/manual-index.html` — the manual CDN dashboard (Babel + React 18, fetches `./data.json`, all logic inside `computeDerived()` / `AttendanceDashboard` in `frontend/index.html:58`). Theme source: `frontend/reference/manual-index.html:100` colors `ink/paper/panel/line/muted/good/alert/warn/neutral/select/exempt`, Fraunces + IBM Plex.
* `frontend/reference/AttendanceDashboard_7.jsx:2` — same dashboard as ES module with `recharts` (`BarChart`/`LineChart`/`ResponsiveContainer`). This is the base to keep — `frontend/index.html:113` SVG charts are the CDN fallback; the JSX version is production-ready.
* `data/MSFT Engineering Resource List - 2026-2.xlsx` stays in `data/` (teams/role/shift seed). `data/data.json` stays gitignored (` .gitignore:2`) — real PII, not committed.

## 2. Goals for Phase 2

1. Drop the `data.json` bind-mount and make the dashboard fetch from the API.
2. Keep the exact theme/structure the user already approved — no redesign.
3. Migrate frontend from `nginx:alpine` static + Babel CDN to Vite + React + recharts so the JSX file becomes the actual app (needed for API calls, env, build).
4. Keep it read-only, no role caps; dev-only fixes stay in DB.

## 3. Out of scope for Phase 2 (pushed)

* Zoho sync (employees/leave/holidays), biometric ingestion, Entra ID activation — Phase 3 once credentials/endpoint known.
* `employee_history` / `shift_templates` matching / `audit_log` writes — stay NULL/empty.
* Auth enforcement — leave `AUTH_REQUIRED=false` until Google flow verified.

## 4. Detailed tasks

### 4.1 Frontend scaffolding

* `frontend/package.json` — `vite`, `react@18`, `react-dom@18`, `recharts`, `axios` or `fetch` wrapper.
* `frontend/vite.config.js` — proxy `/api` → `http://api:8000` inside docker network, `http://localhost:8001` from host.
* `frontend/src/` — move `frontend/reference/AttendanceDashboard_7.jsx` → `frontend/src/AttendanceDashboard.jsx` as `src/main.jsx` entry. Strip the hardcoded `const RAW = [...]` (`frontend/reference/AttendanceDashboard_7.jsx:4`), replace with props.
* Keep `frontend/reference/` untouched as reference — do not delete.

### 4.2 API adapter (the only real code change)

Current dashboard expects flat array per `frontend/reference/AttendanceDashboard_7.jsx:4`:
`[employee_id, name, date, in_time, out_time, work_hours, overtime, late_in, early_out, present, team, leaveStatus, hasLeaveData, exemptionReason]`

API returns normalized JSON from `api/app/main.py:88`:
`GET /attendance` → `{employee_id, employee_name, date, check_in, check_out, work_hours, overtime_hours, late_in, early_out, present, team_name, ...}`
`GET /leave` → `{employee_id, date, leave_type, status}`
`GET /teams` → `[{id, name}]`
`GET /employees` → `[{id, name, current_role, current_shift}]`

Adapter in `src/api.js`:
```js
async function fetchAttendance({date_from, date_to, team_id}) {
  const [att, leave] = await Promise.all([
    fetch(`/api/attendance?date_from=${date_from}&...`).then(r=>r.json()),
    fetch(`/api/leave?date_from=${date_from}&...`).then(r=>r.json())
  ]);
  // join leave onto attendance by (employee_id,date) -> leaveStatus
  // hasLeaveData = true if leave API returned data for that employee/date or team
  // exemption = leave_type where present==false && exemption semantics
  return att.map(a => [
    a.employee_id, a.employee_name, a.date,
    a.check_in?.slice(0,5) ?? null, a.check_out?.slice(0,5) ?? null,
    Number(a.work_hours), Number(a.overtime_hours),
    a.late_in?1:0, a.early_out?1:0, a.present?1:0,
    a.team_name, leaveFor(a), 1, exemptionFor(a)
  ]);
}
```
* Week calculation and `dayStatus()` (`frontend/reference/AttendanceDashboard_7.jsx:36`) stay verbatim — they already implement present/exempt/approved/unauthorized/unverified.
* Components `TrendLineChart`, `StackedBarChart`, `DayChips` keep colors/constants `frontend/reference/AttendanceDashboard_7.jsx:83`.

### 4.3 Docker changes

* `frontend/Dockerfile` — change from `nginx:alpine` to multi-stage: `node:20-alpine` build → `nginx:alpine` serve `dist/`. For dev, add `frontend-dev` service with `vite --host 0.0.0.0 --port 3001` and HMR.
* `docker-compose.yml:60` — remove `volumes: - ./data/data.json:/usr/share/nginx/html/data.json:ro` (no longer needed). Add `VITE_API_URL` env.
* Keep host ports `3001/8001/8002/5434`.

### 4.4 Backend (tiny)

* No schema change needed. Optionally add `GET /attendance/summary?date_from&date_to&team_id` if frontend needs aggregated counts, but Phase 2 can compute client-side as it does now.
* Ensure `api/app/main.py:21` CORS still `allow_origins=["*"]` for Vite dev; tighten later.
* Verify `frontend/reference/AttendanceDashboard_7.jsx:54` weekday filtering — API can add `exclude_weekends=true` param later, for now filter client-side.

### 4.5 Data seeding (optional)

* If Zoho not ready, seed `employees.current_team_id/current_role/current_shift` from `data/MSFT Engineering Resource List - 2026-2.xlsx` (Resource List: Team→Resource→Shift, Categories: Role/Shift). One-off script similar to `scripts/load_data.py:44`.

## 5. Acceptance criteria

* `http://localhost:3001` renders the same dashboard (same colors, tables, week pills, team filter, employee drill-down, charts) but data comes from `http://localhost:8001` — stopping `api` shows error state, not silent empty.
* No `data.json` bind mount; `data/data.json` still works via loader only.
* `npm run build` inside `frontend/` produces `dist/` served by nginx; `docker compose up --build` still one command.
* No new commits of `data/data.json` (still ignored), `frontend/reference/` preserved.

## 6. After Phase 2

* Phase 3: Zoho OAuth (api-console.zoho.com, refresh token in env), scheduled sync `Zoho employees/teams → leave/holidays → biometric` (FK order `db/init.sql:52`), reconcile + `sync_log:109` status partial/failed handling.
* Phase 4: Entra ID switch (`ENTRA_TENANT_ID` etc.) + flip `AUTH_REQUIRED=true` (still flat viewer role, no caps).
