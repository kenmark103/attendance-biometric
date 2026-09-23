# Attendance System — local dev

## Run it

```bash
cp .env.example .env
# generate AUTH_SECRET: python -c "import secrets; print(secrets.token_hex(32))"

docker compose up -d --build
```

Load your data — **this is now a plain HTTP client using only the Python
standard library, no pip install at all**, so it can't hit the PyPI/SSL
build failure a `loader` Docker service used to:

```bash
python scripts/load_data.py data/data.json
```

It POSTs to the already-running `api` container's `/attendance/bulk` and
`/leave/bulk` endpoints, which handle team/employee upserts and chunked
inserts internally. Any Python 3 on your machine works — nothing to build.

Check it:
```bash
curl http://localhost:8001/health
curl "http://localhost:8001/attendance?date_from=2026-08-01&date_to=2026-08-03"
```

API docs: `http://localhost:8001/docs`

## Why there's no `loader` service anymore

There used to be one, built from the same Dockerfile as `api`. Two
problems with that: Compose tagged it as a **separate** image
(`attendance-system-loader`, not reusing `attendance-system-api`), so it
rebuilt from scratch — and on this network, that rebuild's `pip install`
step fails with a TLS handshake error against `files.pythonhosted.org`
(a proxy/firewall issue on the office network, not a bug in the Dockerfile).

Routing ingestion through `/attendance/bulk` instead removes the problem
structurally: the script talking HTTP+JSON needs no dependencies beyond
what ships with Python, so there's no build step left to fail. This also
means the same two endpoints are ready for real biometric/Zoho ingestion
later — same trust-tier discipline, `source` is a property of the whole
batch call, never a per-row field the caller sets.

## Project name pinned

`name: attendance-system` is set explicitly at the top of
`docker-compose.yml`. Without it, Compose derives the image-tag prefix
from whatever folder the repo happens to be cloned into — which is what
caused the `attendance-system-*` vs `attendance-biometric-*` mismatch
earlier. This repo can now be cloned into any folder name safely.

## What's still stubbed, and why

- **`employee_history`, `shift_templates` matching, `holidays`** — tables
  exist, nothing populates them yet. They activate once Zoho's
  employee/shift/holiday sync exists — nothing to match or populate
  against until then.
- **`audit_log`** — table exists, nothing writes to it. Wire it in once
  there's a real manual-override path to audit.
- **Real biometric ingestion** — no code yet; same `/attendance/bulk`
  endpoint the loader uses is the intended target, with `source='biometric'`
  once the COSEC device is reachable and its payload format is confirmed.
- **CORS wide open, `AUTH_REQUIRED=false` by default** — fine for
  localhost, not for anywhere reachable outside your machine.

## Re-running the loader

Upserts on `(employee_id, date)` for attendance and
`(employee_id, date, leave_type)` for leave — safe to re-run against an
updated `data.json`.
