"""Bootstrap admin: seeded from env at startup if no local admin exists.
Break-glass and test login. Changing the env password later does NOT
overwrite an existing admin. The bootstrap email must not be a real Entra
email, because SSO never merges into local accounts."""
from app.auth.security import hash_password
from app.core import settings
from app.core.db import get_conn


def ensure_bootstrap_admin() -> str | None:
    email = (settings.BOOTSTRAP_ADMIN_EMAIL or "").strip().lower()
    password = settings.BOOTSTRAP_ADMIN_PASSWORD or ""
    if not email or not password:
        return None
    if len(password) < 12:
        print("BOOTSTRAP_ADMIN_PASSWORD shorter than 12 chars — skipping seed.")
        return None
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM users WHERE role = 'admin' AND auth_provider = 'local'"
            " AND is_active = TRUE LIMIT 1",
        )
        if cur.fetchone():
            cur.close()
            return None
        cur.execute(
            "INSERT INTO users (email, display_name, role, auth_provider,"
            " password_hash, must_change_password)"
            " VALUES (%s, 'Bootstrap admin', 'admin', 'local', %s, FALSE)"
            " ON CONFLICT (email) DO NOTHING",
            (email, hash_password(password)),
        )
        conn.commit()
        cur.close()
        print(f"Seeded bootstrap admin {email}.")
        return email
    finally:
        conn.close()
