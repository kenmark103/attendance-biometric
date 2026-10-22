# Authentication and WFH audit

## Phase 1 verdict

| Check | Verdict | Result |
| --- | --- | --- |
| A1 JWT signing | FIX | Application JWT algorithm, issuer, audience and secret are typed settings. |
| A2 Claims | FIX | App JWTs require `sub`, `exp`, `iat`, `iss`, `aud`, `role` on decode. |
| A3 lifetimes | FIX | Access tokens default to 30 minutes (maximum 60); refresh families have idle and absolute caps. |
| A4 password hashing | PASS/FIX | Argon2id is retained; rehash and configurable lockout are used. |
| A5 Google | PASS | No Google auth path exists. |
| A6 OIDC | FIX | Entra callback uses signed transaction cookie, PKCE, nonce and JWKS validation. |
| A7 guards | FIX | Viewer/Admin dependencies are explicit; a route inventory test remains required before release. |
| A8 users | FIX | Migration normalises roles to `Viewer`/`Admin`; Entra identity is stable by `entra_oid`. |
| A9 CORS | FIX | Explicit configured origins with credentials are enabled. |
| A10 config | FIX | `Settings` is the one typed environment source. |
| A11 errors | FIX | Auth distinguishes 401 session failures from 403 authorization failures without token details. |
| A12 storage | PASS | Access token is held only in browser memory. |
| A13 actual lifetime | FIX | Before change, `ACCESS_TTL_SECONDS=900` and decoded `exp - iat=900`; perceived longevity came from automatic refresh plus no idle handling. |
| A14 roles | FIX | Migration removes `manager`; existing unexpected values become `Viewer`. The inspected database had zero manager users. |

## Decisions and findings

- Vite/React is retained, as required by the updated specification.
- The app normally uses a same-origin `/api` reverse proxy. CORS remains explicitly configured for local split-origin development; cross-origin cookies require `COOKIE_SAMESITE=none` and `COOKIE_SECURE=true`.
- `wfh_approvals` was counted before work began: zero rows. Migration 010 removes it and its down migration recreates only its empty schema.
- WFH self-approval is allowed and both creator and approver are retained for auditability.
- The dashboard default period is calculated in `frontend/src/filters.js`; it remains unchanged by this work.

## Route protection

Public: `/health`, `/ready`, and login/OIDC routes under `/auth`.

Authenticated: `/auth/me`, `/auth/logout`, and `/auth/change-password`.

Viewer: all attendance, metrics, roster, team, employee and WFH-policy read routes.

Admin: all writes, imports, ingestion triggers, users, audit-event/audit-log reads, and WFH mutations.

## Operational notes

Entra role changes take effect on the next Entra sign-in. `ENTRA_REAUTH_DAYS` bounds how long a prior Entra session can continue through refresh. Audit rows contain metadata, never tokens, passwords, or leave rows.
