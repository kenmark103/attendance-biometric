# Microsoft Entra ID handoff — Attendance Dashboard

## Purpose and agreed scope

This is the implementation handoff for the Microsoft 365 / Entra administrator and the application owner. The current release has exactly two application roles.

| Role | Intended people | Can access | Cannot access or change |
| --- | --- | --- | --- |
| `Viewer` | Jackson Kariuki (IT), Rakesh (Finance), and approved readers | Dashboard and all read-only views: overview, teams, employees, exceptions, data health, attendance/leave/holiday data, and read-only WFH-policy/recall data. Leave is presented as generic **On leave**, not a leave type. | User administration; audit/authentication logs; imports; manual attendance or leave writes; device sync; and every WFH-policy/recall write, approval, or deletion. |
| `Admin` | Rahul, Agnes, Brian Nyilima, and the designated system owner | Everything a Viewer can see, plus user administration, auth/audit logs, data imports and attendance writes, on-demand device sync, leave import lifecycle, and WFH-policy/recall management. | Entra tenant administration, app-registration edits, group membership, app-role definitions, consent, or client-secret rotation. Those remain M365/Entra-admin duties. |

`Admin` wins if a person has both roles. A user with neither role is denied.

### Deferred role: Editor

Do **not** create or assign `Editor` yet. The current database, API guards, UI, and Entra resolver recognize only `Viewer` and `Admin`; adding an Entra Editor role now would not grant usable access. Once the product owner defines Editor's specific boundaries, add it end-to-end in a separate change (database, API guards, UI, tests, Entra app role, and assignment procedure).

## Entra/M365 administrator checklist

### 1. Create the access groups

In **Microsoft Entra admin center** > **Identity** > **Groups** > **All groups** > **New group**, create two **Security** groups with *Assigned* membership:

| Suggested group | Purpose |
| --- | --- |
| `Attendance Dashboard - Viewers` | Read-only application access |
| `Attendance Dashboard - Administrators` | Full in-app administration |

Add the approved users to the applicable group. Prefer direct rather than nested membership unless the tenant team has verified nested-group behaviour for app-role assignment. An administrator should normally belong only to the Administrator group. Record each group's Object ID in the access register; the IDs are operational references, not current application configuration values.

### 2. Register the application

In **Identity** > **Applications** > **App registrations** > **New registration**, set:

| Field | Required value |
| --- | --- |
| Name | `Attendance Dashboard` |
| Supported account types | **Accounts in this organizational directory only** (single tenant) |
| Redirect platform | **Web** |
| Redirect URI | Add the exact URI or URIs in the table below |

Do not use the SPA platform: this is a server-side authorization-code callback with PKCE and a confidential client secret. After creation, provide the Directory (tenant) ID and Application (client) ID from the Overview page.

#### Redirect URIs

The value must match character-for-character, including scheme, host, port, `/api`, and path. It must point to the browser-facing frontend proxy rather than the API port, so the session cookie is set on the same origin that the application uses.

| Environment | Register in Entra and set as `ENTRA_REDIRECT_URI` |
| --- | --- |
| Local Docker Compose | `http://localhost:3001/api/auth/entra/callback` |
| Local Vite development | `http://localhost:5173/api/auth/entra/callback` |
| Production | `https://<attendance-host>/api/auth/entra/callback` |

Replace `<attendance-host>` with the canonical production DNS name. Do not use an IP address, an internal API URL, or `localhost` for production. Production must use HTTPS.

### 3. Define app roles

In the App Registration, open **App roles** > **Create app role** and create these enabled roles exactly:

| Display name | Allowed member types | Value | Description |
| --- | --- | --- | --- |
| `Viewer` | Users/Groups | `Viewer` | Read-only Attendance Dashboard access |
| `Administrator` | Users/Groups | `Admin` | Full Attendance Dashboard administration |

The **Value** is case-sensitive in this application. Do not use `viewer`, `admin`, `Attendance.Viewer`, or any other variation, and do not create `Editor` yet.

### 4. Create and safeguard the client secret

In **Certificates & secrets** > **New client secret**:

- Name it clearly, e.g. `Attendance Dashboard production`.
- Use the organization's shortest practical expiry (normally no longer than 6–12 months unless policy requires less).
- Copy the secret **Value** once and transfer it only through the approved secret-sharing channel. Secret ID is not sufficient.
- Store it only in the deployment secret store or protected `.env`; never source control, tickets, email, browser code, screenshots, or logs.
- Record secret owner and expiry, schedule rotation before expiry, and during rotation create replacement → deploy it → test login → revoke old secret.

The current design needs no Microsoft Graph delegated or application permissions. It asks only for `openid profile email`, so no Graph admin consent is expected.

### 5. Assign groups to application roles

Open **Enterprise applications** > **Attendance Dashboard** > **Users and groups** > **Add user/group**. This assignment step is required in addition to group and role creation.

1. Assign `Attendance Dashboard - Viewers` to app role `Viewer`.
2. Assign `Attendance Dashboard - Administrators` to app role `Administrator` (value `Admin`).
3. If **Assignment required?** appears in Enterprise application > **Properties**, set it to **Yes**. Entra then rejects unassigned users before the app, and the app independently denies missing roles.
4. Pilot with one viewer and one admin before broad assignment.

For an emergency exception, assign an individual directly to the app role and record the owner, reason, and expiry. Groups remain the normal path.

### 6. Provide this completion package

- Tenant ID and Client ID.
- Secret **Value** via approved secure channel.
- Exact redirect URI registered per environment.
- Group names, object IDs, app-role assignments, and membership record.
- Confirmation that the only app-role values are exactly `Viewer` and `Admin`.
- Secret expiry, owner, rotation process, and a named Entra contact for conditional-access or sign-in failures.

## Application-owner setup

### 1. Configure the environment

Copy `.env.example` to `.env` if necessary. Never commit `.env`. These are placeholders, not values to reuse:

```dotenv
APP_ENV=dev
FRONTEND_URL=http://localhost:3001
CORS_ALLOWED_ORIGINS=http://localhost:3001
COOKIE_SECURE=false
COOKIE_SAMESITE=lax

ENTRA_ENABLED=true
ENTRA_TENANT_ID=11111111-2222-3333-4444-555555555555
ENTRA_CLIENT_ID=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
ENTRA_CLIENT_SECRET=<secret-value-from-Entra>
ENTRA_REDIRECT_URI=http://localhost:3001/api/auth/entra/callback
ENTRA_ROLE_SOURCE=roles
ENTRA_ROLE_ADMIN=Admin
ENTRA_ROLE_VIEWER=Viewer
ENTRA_REAUTH_DAYS=7
```

In production, use `APP_ENV=prod`, canonical public HTTPS values, `COOKIE_SECURE=true`, and explicit `CORS_ALLOWED_ORIGINS`. Keep `COOKIE_SAMESITE=lax` when the UI and API share the public site. Cross-site hosting needs `COOKIE_SAMESITE=none` and `COOKIE_SECURE=true` plus a deliberate security review.

Keep `ENTRA_ROLE_SOURCE=roles`. Group claims can overflow for users with many group memberships; this application deliberately denies group-overage claims rather than querying Entra. App roles avoid that limitation.

### 2. Start or redeploy locally

```powershell
docker compose up -d --build
docker compose ps
Invoke-WebRequest http://localhost:8001/health | Select-Object -Expand Content
```

For a local Vite server instead of the Compose frontend, use `http://localhost:5173` in both `FRONTEND_URL` and `ENTRA_REDIRECT_URI` (with the same callback path), then:

```powershell
Set-Location frontend
npm install
npm run dev
```

Do not validate SSO with `AUTH_REQUIRED=false`; it deliberately bypasses authorization.

### 3. Migrate an existing database

Fresh databases use the current schema in `db/init.sql`. An existing volume needs migration 010 once before enabling Entra authorization:

```powershell
docker compose up -d db
Get-Content db/migrations/010_entra_auth_wfh.sql |
  docker compose exec -T db psql -U attendance -d attendance
docker compose up -d --build
```

The migration normalizes stored app roles to `Viewer` or `Admin`; it does not change Entra.

## Acceptance and troubleshooting

Use separate pilot accounts and a private browser window for each test:

| Test | Expected result |
| --- | --- |
| Unassigned organization user | Entra or the app denies access; no Viewer role is inferred. |
| Viewer login | Header says `Viewer`; dashboard is readable; Users, WFH administration, Leave data, Audit log, and Auth events are unavailable; writes return HTTP 403. |
| Admin login | Header says `Admin`; admin screens are present and an authorized, non-destructive operation succeeds. |
| Both roles assigned | `Admin` is selected. |
| Role removed | Test a new sign-in; existing Entra refresh sessions are bounded by `ENTRA_REAUTH_DAYS` (default 7 days). |
| Redirect error | Compare Entra registration, `ENTRA_REDIRECT_URI`, and browser URL exactly. |

Local diagnostics:

```powershell
docker compose logs api --tail=100
docker compose exec api python -c "from app.core import settings; print(settings.config.entra_configured, settings.ENTRA_REDIRECT_URI, settings.ENTRA_ROLE_SOURCE)"
```

Never put client secrets, authorization codes, ID/access tokens, or refresh cookies in logs, tickets, commits, or chats.

## Operational ownership

Entra/M365 owns group membership, app-role definitions and assignments, conditional access, tenant-side sign-in investigation, and secret lifecycle. The Attendance Dashboard Admin owns local user records, imports, data changes, and app audits. Entra users are created/updated on successful SSO login and their role refreshes at the next Entra sign-in; a local admin cannot permanently override an Entra-supplied role.
