"""Pure and database-backed WFH exemption resolution."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta


def is_wfh_exempt(employee_id: str, work_date: date, policies: list[dict], recalls: set[tuple[str, date]]) -> bool:
    """Apply the documented precedence without consulting database state."""
    if (employee_id, work_date) in recalls:
        return False
    active = [p for p in policies if p["employee_id"] == employee_id
              and p.get("status") == "approved"
              and p["start_date"] <= work_date
              and (p.get("end_date") is None or p["end_date"] >= work_date)]
    return any(p["type"] == "temporary" for p in active) or any(p["type"] == "default" for p in active)


def exempt_set(conn, start: date, end: date) -> dict[date, set[str]]:
    """Load policy data once and return exempt employees grouped by work date."""
    cur = conn.cursor()
    cur.execute(
        "SELECT employee_id, type, start_date, end_date, status FROM wfh_policies "
        "WHERE status = 'approved' AND start_date <= %s AND (end_date IS NULL OR end_date >= %s)",
        (end, start),
    )
    policies = [dict(row) for row in cur.fetchall()]
    cur.execute("SELECT employee_id, date FROM wfh_recalls WHERE date BETWEEN %s AND %s", (start, end))
    recalls = {(row["employee_id"], row["date"]) for row in cur.fetchall()}
    cur.close()
    result: dict[date, set[str]] = defaultdict(set)
    day = start
    while day <= end:
        for policy in policies:
            if is_wfh_exempt(policy["employee_id"], day, policies, recalls):
                result[day].add(policy["employee_id"])
        day += timedelta(days=1)
    return dict(result)
