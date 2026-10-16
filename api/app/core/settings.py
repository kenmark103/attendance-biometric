"""Central settings. Plain os.environ, matching this repo's style
(no pydantic settings module). Follows the auth env contract.

JWT_SECRET must be 32+ chars — the app refuses to start otherwise.
"""
import os


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


JWT_SECRET = _get("JWT_SECRET", "")
ACCESS_TTL_SECONDS = int(_get("ACCESS_TTL_SECONDS", "900") or 900)
REFRESH_TTL_DAYS = int(_get("REFRESH_TTL_DAYS", "7") or 7)
REFRESH_ABSOLUTE_DAYS = int(_get("REFRESH_ABSOLUTE_DAYS", "30") or 30)
COOKIE_SECURE = _get("COOKIE_SECURE", "false").lower() == "true"

ENTRA_TENANT_ID = _get("ENTRA_TENANT_ID", "").strip()
ENTRA_CLIENT_ID = _get("ENTRA_CLIENT_ID", "").strip()
ENTRA_CLIENT_SECRET = _get("ENTRA_CLIENT_SECRET", "")
ENTRA_REDIRECT_URI = _get(
    "ENTRA_REDIRECT_URI", "http://localhost:8001/auth/microsoft/callback"
).strip()

BOOTSTRAP_ADMIN_EMAIL = _get("BOOTSTRAP_ADMIN_EMAIL", "admin@attendance.internal").strip().lower()
BOOTSTRAP_ADMIN_PASSWORD = _get("BOOTSTRAP_ADMIN_PASSWORD", "")

DATABASE_URL = _get("DATABASE_URL", "postgresql://attendance:attendance@db:5432/attendance")

# Legacy knob from the pre-auth era. Auth routes are always mounted;
# this only gates whether data endpoints still accept anonymous traffic.
# Default true once auth lands — set explicitly to "false" for open dev.
AUTH_REQUIRED = _get("AUTH_REQUIRED", "true").lower() == "true"

# --- Leave ingestion (spec §§3, 9, 12) ------------------------------------
# EXPECTED_DEPARTMENT_LABELS is ';'-separated (the label itself contains a
# comma). TRUST_ZOHO_PRESENCE gates `present_zoho_only`; LEAVE_SOURCE_PRIORITY
# orders 'api' over 'xls' when both exist; LEAVE_TYPE_DETAIL_ROLES gates
# sick/maternity/paternity detail (default admin); MIN_PUNCH_MINUTES matches
# the repo's punch definition (default 0 = any punch counts).
EXPECTED_DEPARTMENT_LABELS = [
    s.strip() for s in _get(
        "EXPECTED_DEPARTMENT_LABELS",
        "GBS- ENGINEERING CENTRE,Engineering Centre").split(";") if s.strip()
]
TRUST_ZOHO_PRESENCE = _get("TRUST_ZOHO_PRESENCE", "true").lower() == "true"
LEAVE_SOURCE_PRIORITY = [
    s.strip() for s in _get("LEAVE_SOURCE_PRIORITY", "api,xls").split(",") if s.strip()
]
LEAVE_TYPE_DETAIL_ROLES = [
    s.strip() for s in _get("LEAVE_TYPE_DETAIL_ROLES", "admin").split(",") if s.strip()
]
MIN_PUNCH_MINUTES = int(_get("MIN_PUNCH_MINUTES", "0") or 0)
LEAVE_UPLOAD_MAX_MB = int(_get("LEAVE_UPLOAD_MAX_MB", "10") or 10)


def entra_configured() -> bool:
    return bool(ENTRA_TENANT_ID and ENTRA_CLIENT_ID and ENTRA_CLIENT_SECRET)


def validate_startup() -> None:
    if len(JWT_SECRET) < 32:
        raise RuntimeError(
            "JWT_SECRET must be at least 32 characters. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
