"""Pure tests for the backend metrics core (spec §2.3 examples A-E plus the
extra Phase 2 cases). No DB, no HTTP.

Run: docker compose exec api pytest tests/test_metrics_core.py -v
"""
from datetime import date, time

from app.metrics.core import (
    build_metrics,
    build_roster,
    roster_csv,
    team_slug,
)

# Wed 2026-09-09, Sat 2026-09-12, Thu 2026-09-10.
WED = date(2026, 9, 9)
THU = date(2026, 9, 10)
SAT = date(2026, 9, 12)
TODAY = date(2026, 9, 20)
COVERED = date(2026, 9, 30)


def emp(i, team="A", shift="day"):
    return {"id": f"e{i}", "name": f"Emp {i:03d}", "team": team, "shift": shift}


def punch(present=True, check_in=time(8, 0), check_out=time(17, 0), source="biometric"):
    return {
        "check_in": check_in, "check_out": check_out, "present": present,
        "work_hours": 8.0, "overtime_hours": 0.0, "late_in": False,
        "early_out": False, "source": source,
    }


def run(employees, records=(), leave=(), holidays=(), coverage=None,
        start=WED, end=None, **kw):
    recs = {(eid, d): r for eid, d, r in records}
    cals = {}
    for eid, d in leave:
        cals[(eid, d)] = {"kind": "leave", "fraction": 1.0,
                          "zoho_presence": None, "leave_type": "Annual"}
    return build_metrics(
        employees=employees, records=recs, calendar=cals,
        leave_dates=set(leave), holidays=set(holidays),
        coverage_through=coverage, start=start, end=end or start, today=TODAY,
        **kw)


def test_example_a_leave_not_loaded():
    employees = [emp(i) for i in range(10)]
    records = [(f"e{i}", WED, punch()) for i in range(7)]
    m = run(employees, records, coverage=None)
    s = m["summary"]
    assert s["present_days"] == 7
    assert s["unverified_days"] == 3
    assert s["on_leave_days"] == 0
    assert s["absent_days"] == 0
    assert round(s["attendance_rate"], 3) == 0.700
    assert s["is_provisional"] is True
    assert s["provisional_days"] == 1


def test_example_b_leave_covers_the_date():
    employees = [emp(i) for i in range(10)]
    records = [(f"e{i}", WED, punch()) for i in range(7)]
    leave = [(f"e{i}", WED) for i in range(7, 8)]  # one non-puncher on leave
    m = run(employees, records, leave=leave, coverage=COVERED)
    s = m["summary"]
    assert s["present_days"] == 7
    assert s["on_leave_days"] == 1
    assert s["absent_days"] == 2
    assert round(s["attendance_rate"], 4) == 0.7778
    assert s["is_provisional"] is False


def test_example_c_realistic_scale():
    employees = [emp(i) for i in range(132)]
    records = [(f"e{i}", WED, punch()) for i in range(99)]
    leave = [(f"e{i}", WED) for i in range(99, 111)]  # 12 on leave
    m = run(employees, records, leave=leave, coverage=COVERED)
    s = m["summary"]
    assert s["headcount"] == 132
    assert s["present_days"] == 99
    assert s["on_leave_days"] == 12
    assert s["absent_days"] == 21
    assert round(s["attendance_rate"], 3) == 0.825

    before = run(employees, records, coverage=None)["summary"]
    assert round(before["attendance_rate"], 3) == 0.750
    assert before["unverified_days"] == 33


def test_example_d_sync_outage_is_no_data():
    employees = [emp(i) for i in range(10)]
    m = run(employees, records=[], coverage=COVERED)
    s = m["summary"]
    assert s["no_data_days"] == 1
    assert s["present_days"] == 0
    assert s["attendance_rate"] is None
    assert m["daily"][0]["state"] == "no_data"
    assert m["daily"][0]["attendance_rate"] is None
    assert all(e["days"][0]["status"] == "no_data" for e in m["employees"])


def test_example_e_punch_overrides_leave():
    employees = [emp(0), emp(1)]
    records = [("e0", WED, punch())]
    leave = [("e0", WED)]  # punched AND on leave
    m = run(employees, records, leave=leave, coverage=COVERED)
    e0 = next(e for e in m["employees"] if e["id"] == "e0")
    assert e0["days"][0]["status"] == "present"
    assert e0["days"][0]["leave_conflict"] is True
    assert m["summary"]["on_leave_days"] == 0
    assert m["summary"]["leave_conflict_days"] == 1


def test_weekend_and_holiday_excluded():
    employees = [emp(i) for i in range(4)]
    weekend = run(employees, records=[("e0", SAT, punch())], start=SAT)
    assert weekend["summary"]["attendance_rate"] is None
    assert weekend["daily"] == []
    assert all(e["days"][0]["status"] == "non_working"
               for e in weekend["employees"])

    holiday = run(employees, records=[("e0", THU, punch())], holidays=[THU],
                  start=THU)
    assert holiday["summary"]["attendance_rate"] is None
    assert all(e["days"][0]["status"] == "non_working"
               for e in holiday["employees"])


def test_team_filter_changes_rate_not_no_data():
    employees = [emp(i, team="A") for i in range(5)] + \
                [emp(100 + i, team="B") for i in range(5)]
    records = [(f"e{i}", WED, punch()) for i in range(5)]  # only team A punched
    full = run(employees, records, coverage=COVERED)["summary"]
    assert round(full["attendance_rate"], 3) == 0.5
    assert full["no_data_days"] == 0

    team_b = run(employees, records, coverage=COVERED, team_filter={"B"})
    assert team_b["summary"]["headcount"] == 5
    assert team_b["summary"]["attendance_rate"] == 0.0
    # no_data is an org-wide fact: team B having no punches does not make it
    # a no_data date.
    assert team_b["summary"]["no_data_days"] == 0
    assert team_b["daily"][0]["state"] == "covered"


def test_month_rate_is_ratio_of_sums_not_mean():
    employees = [emp(i) for i in range(10)]
    day1, day2 = WED, THU
    records = [(f"e{i}", day1, punch()) for i in range(8)]
    records += [(f"e{i}", day2, punch()) for i in range(2)]
    leave = [(f"e{i}", day1) for i in range(8, 10)]  # 2 on leave day1
    m = run(employees, records, leave=leave, coverage=COVERED,
            start=day1, end=day2)
    daily_rates = [d["attendance_rate"] for d in m["daily"]]
    mean_of_daily = sum(daily_rates) / len(daily_rates)
    assert round(daily_rates[0], 1) == 1.0   # 8 / (10 - 2)
    assert round(daily_rates[1], 1) == 0.2   # 2 / (10 - 0)
    assert round(mean_of_daily, 3) == 0.600
    # sum ratio: 10 present / (20 expected - 2 on_leave) = 0.5556
    assert round(m["summary"]["attendance_rate"], 4) == 0.5556


def test_zero_denominator_returns_null():
    assert run([], records=[])["summary"]["attendance_rate"] is None

    # All of the filtered team is on leave; another team punched, so the date
    # is not no_data but the chosen team's denominator is zero.
    employees = [emp(i, team="A") for i in range(3)] + [emp(50, team="B")]
    records = [("e50", WED, punch())]
    leave = [(f"e{i}", WED) for i in range(3)]
    m = run(employees, records, leave=leave, coverage=COVERED,
            team_filter={"A"})
    assert m["summary"]["headcount"] == 3
    assert m["summary"]["attendance_rate"] is None


def test_roster_night_shift_and_status_filter():
    employees = [emp(0, team="Eng"), emp(1, team="Eng"), emp(2, team="Ops")]
    records = [
        ("e0", WED, punch(check_in=time(22, 0), check_out=time(2, 0))),
        ("e2", WED, punch()),
    ]
    leave = [("e1", WED)]
    r = build_roster(
        employees=employees,
        records={(eid, d): rec for eid, d, rec in records},
        calendar={(eid, d): {"kind": "leave", "fraction": 1.0,
                             "zoho_presence": None, "leave_type": "Annual"}
                  for eid, d in leave},
        leave_dates=set(leave), holidays=set(), coverage_through=COVERED,
        d=WED, today=TODAY)
    assert r["date_state"] == "covered"
    by_id = {row["employee_id"]: row for row in r["rows"]}
    assert by_id["e0"]["first_punch"] == "22:00"
    assert by_id["e0"]["last_punch"] == "02:00"
    assert by_id["e1"]["status"] == "on_leave"

    present_only = build_roster(
        employees=employees,
        records={(eid, d): rec for eid, d, rec in records},
        calendar={}, leave_dates=set(), holidays=set(),
        coverage_through=COVERED, d=WED, today=TODAY,
        statuses={"present"})
    assert {row["employee_id"] for row in present_only["rows"]} == {"e0", "e2"}


def test_roster_no_data_and_non_working():
    employees = [emp(0)]
    no_data = build_roster(employees=employees, records={}, calendar={},
                           leave_dates=set(), holidays=set(),
                           coverage_through=COVERED, d=WED, today=TODAY)
    assert no_data["date_state"] == "no_data"
    assert no_data["rows"] == []

    weekend = build_roster(employees=employees, records={}, calendar={},
                           leave_dates=set(), holidays=set(),
                           coverage_through=COVERED, d=SAT, today=TODAY)
    assert weekend["date_state"] == "non_working"


def test_roster_csv_escapes_formula_injection():
    employees = [emp(0)]
    records = [("e0", WED, punch())]
    r = build_roster(employees=employees,
                     records={(eid, d): rec for eid, d, rec in records},
                     calendar={}, leave_dates=set(), holidays=set(),
                     coverage_through=COVERED, d=WED, today=TODAY)
    r["rows"][0]["name"] = "=cmd|' /C calc'!A0"
    text = roster_csv(r)
    assert text.startswith("employee_id,name,team,status")
    assert "'=cmd" in text
    assert "\r\n" in text


def test_team_slug_matches_frontend_shape():
    assert team_slug("GBS- ENGINEERING CENTRE") == "gbs-engineering-centre"
    assert team_slug("Engineering Centre") == "engineering-centre"
    assert team_slug("") == "unassigned"
