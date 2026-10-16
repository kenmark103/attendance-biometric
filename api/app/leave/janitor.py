"""Leave-import janitor: failure marking and preview expiry (spec §8).

Runs at API startup and at the start of every upload (cheap, idempotent):
- `parsing` rows older than 15 minutes are stuck -> `failed`.
- `committing` rows are stale (their transaction rolled back on restart) -> `failed`.
- `preview_ready` rows past `expires_at` (24 h) -> `expired`, with staging
  purged and preview names nulled.
"""
from __future__ import annotations


def run_janitor(conn) -> dict:
    cur = conn.cursor()
    cur.execute(
        """UPDATE leave_import SET status = 'failed',
               error_id = COALESCE(error_id, 'janitor: stuck parsing')
           WHERE status = 'parsing' AND uploaded_at < now() - interval '15 minutes'""")
    stuck = cur.rowcount
    cur.execute(
        """UPDATE leave_import SET status = 'failed',
               error_id = COALESCE(error_id, 'janitor: stale committing')
           WHERE status = 'committing'""")
    stale = cur.rowcount
    cur.execute("SELECT id FROM leave_import "
                "WHERE status = 'preview_ready' AND expires_at < now()")
    expired_ids = [r["id"] for r in cur.fetchall()]
    for import_id in expired_ids:
        cur.execute("DELETE FROM leave_import_staging WHERE import_id = %s",
                    (import_id,))
        cur.execute("UPDATE leave_import SET status = 'expired', preview_names = NULL "
                    "WHERE id = %s", (import_id,))
    # Failed previews keep no staging either (issues stay for history).
    cur.execute("SELECT id FROM leave_import WHERE status = 'failed'")
    for r in cur.fetchall():
        cur.execute("DELETE FROM leave_import_staging WHERE import_id = %s", (r["id"],))
        cur.execute("UPDATE leave_import SET preview_names = NULL WHERE id = %s",
                    (r["id"],))
    cur.close()
    if stuck or stale or expired_ids:
        print(f"leave janitor: {stuck} stuck, {stale} stale, "
              f"{len(expired_ids)} expired")
    return {"stuck_parsing": stuck, "stale_committing": stale,
            "expired": len(expired_ids)}
