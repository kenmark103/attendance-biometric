# Attendance System

Biometric + Zoho attendance dashboard (FastAPI + Postgres + Vite React).

## Run it on any machine

Prereqs: Docker + Docker Compose, any Python 3 (for the loader script only).

```bash
git clone <this-repo> && cd <repo>
cp .env.example .env
# edit .env and set:
#   JWT_SECRET=            <- required, 32+ chars. Generate:
#                             python -c "import secrets; print(secrets.token_hex(32))"
#   BOOTSTRAP_ADMIN_PASSWORD=  <- required, 12+ chars (first admin login)
#   ENTRA_*                <- leave blank until IT provisions the App Registration;
#                             email/password login works without it

docker compose up -d --build
```

Fresh database? The schema (including auth tables) is created automatically
by `db/init.sql`. **Existing** database from before auth? Apply the
one-time migration once:

```bash
docker compose exec -T db psql -U attendance -d attendance \
  -f /dev/stdin < db/migrations/004_auth.sql
```

Load data (needs `data/data.json`, gitignored — never committed):

```bash
python scripts/load_data.py data/data.json
# or: docker compose --profile tools run --rm loader
```

Open `http://localhost:3001`, sign in with email as
`admin@attendance.internal` (the bootstrap admin). API health:
`http://localhost:8001/health`. API docs: `http://localhost:8001/docs`.

Ports (host): `5434` postgres, `8001` api, `3001` frontend. The browser
only ever talks to `:3001` — the frontend proxies `/api/*` to the API on
the same origin, so auth cookies work with no CORS.

## Auth in one paragraph

Two login methods, one session shape: Microsoft Entra SSO (single tenant)
plus admin-created local email/password accounts. Both end in our own
HS256 JWT (15 min, browser memory only) + rotating opaque refresh cookie
(`httpOnly`, 7-day sliding / 30-day absolute). Roles `admin > manager >
viewer`: SSO users get them from Entra App Roles (else a pre-created DB
row, else denied); local users from the DB. Every request re-reads the
user row, so deactivation/role changes apply immediately. `users`
(system logins) is a different table from `employees` (attendance
subjects) — manage logins on the in-app Users page (admin only).

Reset a password: `docker exec <api> python -m app.auth.cli
reset-admin-password <email>` (reads from `NEW_PASSWORD` env or prompt).

## Backend layout (`api/app/`)

```
main.py            app factory, router wiring, lifespan startup, /health
core/              settings (env), db (psycopg2 pool-less helper),
                   deps (current_user, require_role, viewer/manager/admin)
auth/              security (argon2id, JWT, refresh hashing),
                   sessions (issue/rotate/revoke + cookies + audit),
                   local (login/refresh/logout/me/change-password),
                   microsoft (Entra PKCE login + callback),
                   admin (/users CRUD, /auth/events),
                   bootstrap (first-admin seed), cli (password reset)
routers/           schemas (pydantic), attendance (teams/employees/records,
                   leave/holidays/coverage/sync-log/bulk), wfh (approvals)
ingestion/         COSEC biometric sync worker (polls device -> staging)
```

Tests: `docker compose exec api pytest tests/ -v` (66 tests: auth per the
implementation guide + ingestion). Auth tests need the compose Postgres.

## Troubleshooting

- **Login page loops / "Could not load from API"**: hard-refresh
  (`Ctrl+Shift+R`). `index.html` is served no-cache, but a previously
  cached copy may still reference the old direct-to-`:8001` bundle.
- **API container restarting**: almost always `JWT_SECRET` missing/short —
  `docker logs attendance-system-api-1` prints the exact requirement.
- **Ingestor restarting**: missing `COSEC_*` vars used to crash-loop it;
  now it idles in standby until they're set. If vars are set but the
  device IP is unreachable from your network, it logs retries — normal
  until the poller runs on the office network.
- **SSO button errors**: expected until `ENTRA_TENANT_ID/CLIENT_ID/SECRET`
  are set (then it returns 503 `sso_not_configured`). Use email login
  meanwhile.

## Re-running the loader

Upserts on `(employee_id, date)` for attendance and
`(employee_id, date, leave_type)` for leave — safe to re-run against an
updated `data.json`.
