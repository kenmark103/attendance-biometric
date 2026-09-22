# Attendance System — Phase 1 (local dev)

Phase 1 covers: full DB schema, the read API, and an auth service with a
real Google login (for you to learn the OIDC flow) and a config-ready,
currently-inactive Entra ID route. What's still stubbed and why is listed
at the bottom.

## Services

| Service | Host port | Purpose |
|---|---|---|
| `db` | 5434 | Postgres |
| `api` | 8001 | Attendance/leave/holidays API |
| `auth-service` | 8002 | OIDC login (Google now, Entra ID once configured) |
| `frontend` | 3001 | The existing static dashboard |

Ports were remapped off the usual 5432/8000/3000 defaults since those
collide with your other local projects. This only changes what's exposed
to your machine — services still talk to each other inside the docker
network on the standard ports (see `docker-compose.yml`).

## Run it

```bash
cp .env.example .env
# generate AUTH_SECRET: python -c "import secrets; print(secrets.token_hex(32))"
# fill it into .env, leave GOOGLE_*/ENTRA_* blank for now if you're not testing auth yet

mkdir -p data
cp /path/to/your/data.json data/data.json   # do this BEFORE `up` — frontend bind-mounts this exact file

docker compose up -d --build
```

Load that same file into Postgres — **no host `pip install` needed**,
this runs inside a container:

```bash
docker compose --profile tools run --rm loader
```

Check it:

```bash
curl http://localhost:8001/health
curl http://localhost:8001/teams
curl "http://localhost:8001/attendance?date_from=2026-08-01&date_to=2026-08-03"
curl http://localhost:8001/leave
```

API docs: `http://localhost:8001/docs`

## Testing the Google login flow

1. Create OAuth credentials at https://console.cloud.google.com/apis/credentials
   (Web application), redirect URI `http://localhost:8002/auth/callback/google`.
2. Put `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env`, restart:
   `docker compose up -d --build auth-service`
3. Add yourself to the whitelist first — this app is invite-only, so
   authenticating successfully isn't enough on its own:
   ```sql
   INSERT INTO app_users (email, name, role) VALUES ('you@gmail.com', 'Kenny', 'admin');
   ```
4. Visit `http://localhost:8002/auth/login/google` in a browser.

## Switching to Entra ID later

Fill in `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET` in
`.env`, restart `auth-service`. That's the whole change — same OAuth
client code, different discovery URL. `/auth/login/entra` goes from a 501
("not configured") to working the moment those three values are set.

Authorization stays separate from this: whoever logs in still needs a row
in `app_users` with the right role, regardless of which provider they
came through.

## Fetch order, once Zoho/biometric integration exists

Zoho (employees + teams) first, then leave/holidays, then biometric —
in that order, every sync. Employees/teams have to exist before
attendance rows can reference them (foreign keys); trust priority
between sources (biometric wins on presence, Zoho wins on leave context)
is a separate decision made during reconciliation, not during fetch order.

## What's still stubbed, and why

- **`employee_history`** — table exists, not populated. The source JSON
  has no role/shift data to seed it with; it activates once the Zoho
  employee sync exists and can detect real changes over time.
- **`shift_templates`** — seeded with rough windows (day/night/hybrid)
  from what's been discussed, not confirmed numbers. `attendance_records
  .assigned_shift` / `matched_shift` stay NULL until Zoho supplies shift
  assignment — there's nothing to match against yet.
- **`holidays`** — table exists, empty. Populates once the Zoho holiday
  fetch is built. Weekends aren't stored here at all — compute those from
  the date, don't wait on a data source for something derivable.
- **`audit_log`** — table exists, nothing writes to it yet. Wire it in
  once there's an actual manual-override endpoint to audit.
- **Biometric ingestion** — no code for this yet; waiting on the actual
  endpoint format from the senior dev, and on working out network access
  (the device is on a lab-network segment your corp-network machine
  couldn't reach).
- **CORS + `AUTH_REQUIRED=false` by default** — wide open for local dev.
  Do not deploy this configuration anywhere reachable outside your machine.

## Re-running the loader

Upserts on `(employee_id, date)` for attendance, and on
`(employee_id, date, leave_type)` for leave — safe to re-run against an
updated `data.json` without creating duplicates.
