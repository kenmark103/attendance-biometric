"""Admin CLI. Usage:
    docker exec <api> python -m app.auth.cli reset-admin-password admin@attendance.internal
New password comes from the NEW_PASSWORD env var or an interactive prompt.
"""
import getpass
import os
import sys

from app.auth.security import hash_password
from app.auth.sessions import log_event, revoke_all_for_user
from app.core.db import get_conn


def cmd_reset_admin_password(email: str) -> int:
    email = (email or "").strip().lower()
    if "@" not in email:
        print("Provide an email address.", file=sys.stderr)
        return 2
    new_password = os.environ.get("NEW_PASSWORD") or getpass.getpass("New password (12+ chars): ")
    if len(new_password) < 12 or len(new_password) > 128:
        print("Password must be 12-128 characters.", file=sys.stderr)
        return 2
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        if user is None:
            print(f"No user {email}.", file=sys.stderr)
            return 1
        if user["auth_provider"] != "local":
            print(f"{email} is an Entra (SSO) account — no local password to reset.",
                  file=sys.stderr)
            return 1
        cur.execute(
            "UPDATE users SET password_hash = %s, must_change_password = FALSE,"
            " failed_login_count = 0, locked_until = NULL, updated_at = now()"
            " WHERE id = %s",
            (hash_password(new_password), str(user["id"])),
        )
        log_event(cur, user_id=user["id"], email=email,
                  event="password_reset", detail="via cli")
        conn.commit()
        cur.close()
        revoke_all_for_user(conn, user["id"])
        print(f"Password reset for {email}; sessions revoked.")
        return 0
    finally:
        conn.close()


def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if len(argv) == 2 and argv[0] == "reset-admin-password":
        return cmd_reset_admin_password(argv[1])
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
