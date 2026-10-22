from datetime import date

from app.wfh.resolver import is_wfh_exempt


def policy(employee_id, kind, start, end=None, status="approved"):
    return {"employee_id": employee_id, "type": kind, "start_date": start, "end_date": end, "status": status}


def test_temporary_and_default_policies_are_exempt_only_when_approved():
    d = date(2026, 10, 12)
    policies = [
        policy("one", "temporary", date(2026, 10, 10), date(2026, 10, 14)),
        policy("two", "default", date(2026, 10, 1)),
        policy("three", "temporary", date(2026, 10, 1), date(2026, 10, 31), "pending"),
        policy("four", "default", date(2026, 10, 1), status="revoked"),
    ]
    assert is_wfh_exempt("one", d, policies, set())
    assert is_wfh_exempt("two", d, policies, set())
    assert not is_wfh_exempt("three", d, policies, set())
    assert not is_wfh_exempt("four", d, policies, set())


def test_recall_wins_over_every_policy_type():
    d = date(2026, 10, 12)
    policies = [policy("one", "default", date(2026, 1, 1)), policy("one", "temporary", date(2026, 10, 1), date(2026, 10, 31))]
    assert not is_wfh_exempt("one", d, policies, {("one", d)})
