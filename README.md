# Attendance System

Biometric + Zoho attendance dashboard (FastAPI + Postgres + Vite React).

## First-time setup (any machine)

Prereqs: Docker + Docker Compose, any Python 3 (loader script only).

```bash
git clone <this-repo> && cd <repo>
cp .env.example .env
```

Edit `.env` and set (nothing works without these two):

| Variable | What |
| --- | --- |
| `JWT_SECRET` | 32+ random chars. Generate: `python -c "import secrets; print(secrets.token_hex(32))"`. API refuses to start without it. |
| `BOOTSTRAP_ADMIN_PASSWORD` | 12+ chars. First admin login (`BOOTSTRAP_ADMIN_EMAIL`, default `admin@attendance.internal`). |
| `ENTRA_*` | Leave blank until IT provisions the App Registration — email/password login works without it. |

Then:

```bash
docker compose up -d --build
```

Fresh database? Schema (including auth tables) is created automatically
by `db/init.sql`. Load data (`data/data.json` is gitignored, copy it in
yourself — it is never committed):

```bash
python scripts/load_data.py data/data.json
# or: docker compose --profile tools run --rm loader
```

Open `http://localhost:3001` and sign in. API health:
`http://localhost:8001/health`. API docs: `http://localhost:8001/docs`.

## Updating on the office PC (keeps live data)

Your data lives in the **`pgdata` Docker volume**, not in the images.
Rebuilding images never touches it. Safe update:

```bash
git pull
docker compose up -d --build
```

That rebuilds `api` + `frontend` and recreates containers; Postgres data,
including live COSEC rows, stays exactly as it was. Never run
`docker compose down -v` here — the `-v` deletes the volume and your data
with it. (Plain `down` without `-v` is safe; `up` brings it all back.)

Two one-time steps, only if that machine's DB predates auth:

1. **New env vars.** The office `.env` is from before auth — add these
   (values from IT / your own secrets, same meanings as above):
   `JWT_SECRET`, `AUTH_REQUIRED=true`, `ACCESS_TTL_SECONDS=900`,
   `REFRESH_TTL_DAYS=7`, `REFRESH_ABSOLUTE_DAYS=30`,
   `COOKIE_SECURE=false`, `ENTRA_TENANT_ID/CLIENT_ID/CLIENT_SECRET/REDIRECT_URI`
   (may stay blank), `BOOTSTRAP_ADMIN_EMAIL/PASSWORD`.
   The old `AUTH_SECRET` / `GOOGLE_*` lines are dead and can be deleted.
2. **Auth migration.** Start just the DB, apply it, then bring up the rest:
   ```bash
   docker compose up -d db
   docker compose exec -T db psql -U attendance -d attendance \
     -f /dev/stdin < db/migrations/004_auth.sql
   docker compose up -d --build
   ```
   The bootstrap admin is seeded automatically on first API start.

Verify: `http://localhost:3001` login page → sign in with email.

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

Ports (host): `5434` postgres, `8001` api, `3001` frontend. The browser
only ever talks to `:3001` — the frontend proxies `/api/*` to the API on
the same origin, so auth cookies work with no CORS.

Reset a password: `docker exec attendance-system-api-1 python -m
app.auth.cli reset-admin-password <email>` (takes it from the
`NEW_PASSWORD` env var or an interactive prompt; you supply it, so you
know it — other sessions for that user are revoked).

## Backend layout (`api/app/`)

```
main.py            app factory, router wiring, lifespan startup, /health
core/              settings (env), db (psycopg2 helper),
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

Tests: `docker compose exec api pytest tests/ -v` (auth + ingestion, needs
the compose Postgres).

## Troubleshooting

- **Login page loops / "Could not load from API"**: hard-refresh
  (`Ctrl+Shift+R`) once — a previously cached page can reference an old
  bundle. `index.html` is now served no-cache so this shouldn't recur.
- **API container restarting**: almost always `JWT_SECRET` missing/short —
  `docker logs attendance-system-api-1` prints the exact requirement.
- **Ingestor idling**: missing `COSEC_*` vars intentionally park it in
  standby (no more crash-loop). Vars set but device unreachable = retries
  in the logs; normal until it runs on the office network.
- **SSO button errors**: expected until `ENTRA_*` are set (503
  `sso_not_configured`). Use email login meanwhile.

## Re-running the loader

Upserts on `(employee_id, date)` for attendance and
`(employee_id, date, leave_type)` for leave — safe to re-run against an
updated `data.json`.
