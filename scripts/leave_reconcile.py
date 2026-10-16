"""LOCAL reconciliation: Zoho calendar rows vs biometric attendance.

Compares committed calendar_day (xls) against attendance_records over their
overlap. Prints aggregate counts + small ID/date samples (no names).

Local only — output may contain employee IDs for Zoho-UI spot checks.
Never commit the output, never paste it into issues/PRs.

Runs inside the api container (DB access):
    docker compose exec -T api python /scripts/leave_reconcile.py
"""
import sys

sys.path.insert(0, "/app")

from app.core.db import get_conn  # noqa: E402


def key(eid: str) -> str:
    return (eid or "").strip().lstrip("0") or "0"


conn = get_conn()
try:
    cur = conn.cursor()
    cur.execute("SELECT employee_id, date, raw_code, kind, leave_code, zoho_presence,"
                " fraction FROM calendar_day WHERE source = 'xls'")
    cal = cur.fetchall()
    cur.execute("SELECT employee_id, date, check_in, check_out, present FROM attendance_records")
    att = cur.fetchall()
    cur.close()
finally:
    conn.close()

punch = {}
covered_dates = set()
for r in att:
    punched = bool(r["check_in"] or r["check_out"] or r["present"])
    punch[(key(r["employee_id"]), str(r["date"]))] = punched
    covered_dates.add(str(r["date"]))
att_keys = set(punch)

n_a = n_a_punch = 0
n_p = n_p_nopunch = 0
n_p_cov = n_p_cov_nopunch = 0
n_leave = n_leave_punch = 0
by_leave: dict[str, int] = {}
samples_a, samples_p, samples_l = [], [], []
samples_p_cov = []
n_hp = n_wp = n_half = 0
for r in cal:
    k = (key(r["employee_id"]), str(r["date"]))
    has_att = k in att_keys
    punched = punch.get(k, False)
    raw, kind = r["raw_code"], r["kind"]
    covered = str(r["date"]) in covered_dates
    if raw == "A":
        n_a += 1
        if punched:
            n_a_punch += 1
            if len(samples_a) < 20:
                samples_a.append((r["employee_id"], str(r["date"])))
    elif raw == "P":
        n_p += 1
        if not punched:
            n_p_nopunch += 1
            if len(samples_p) < 20:
                samples_p.append((r["employee_id"], str(r["date"]), "no_att_row" if not has_att else "row_no_punch"))
        if covered:
            n_p_cov += 1
            if not punched:
                n_p_cov_nopunch += 1
                if len(samples_p_cov) < 20:
                    samples_p_cov.append((r["employee_id"], str(r["date"])))
    if kind == "leave":
        n_leave += 1
        by_leave[r["leave_code"] or "?"] = by_leave.get(r["leave_code"] or "?", 0) + 1
        if punched or r["zoho_presence"]:
            n_leave_punch += 1
            if len(samples_l) < 20:
                samples_l.append((r["employee_id"], str(r["date"]), raw,
                                  "punch" if punched else "zoho-only"))
    if raw in ("H/P", "W/P"):
        if raw == "H/P":
            n_hp += 1
        else:
            n_wp += 1
    if str(r["fraction"]) == "0.50":
        n_half += 1

cal_ids = {key(r["employee_id"]) for r in cal}
att_ids = {key(r["employee_id"]) for r in att}
print("=== leave-vs-biometric reconciliation ===")
print(f"calendar rows : {len(cal)}  ({min(str(r['date']) for r in cal)}..{max(str(r['date']) for r in cal)})")
print(f"attendance rows: {len(att)}")
print(f"IDs: calendar={len(cal_ids)} attendance={len(att_ids)} "
      f"overlap={len(cal_ids & att_ids)} att-only={len(att_ids - cal_ids)}")
print()
print(f"A. Zoho-A days: {n_a}; with biometric punch: {n_a_punch} "
      f"({n_a_punch / n_a:.1%}) — old Zoho logs under-reported presence" if n_a else "A. no Zoho-A days")
for s in samples_a:
    print(f"   A+punch: {s[0]} {s[1]}")
print()
print(f"B. Zoho-P days: {n_p}; with NO biometric punch: {n_p_nopunch} "
      f"({n_p_nopunch / n_p:.1%}) — mostly dates with no biometric coverage at all" if n_p else "B. no Zoho-P days")
for s in samples_p:
    print(f"   P-only: {s[0]} {s[1]} ({s[2]})")
print(f"B2. on biometrically-covered dates only ({len(covered_dates)} dates): "
      f"Zoho-P={n_p_cov}, no punch={n_p_cov_nopunch} "
      f"({n_p_cov_nopunch / n_p_cov:.1%} — the honest remote/manual share)" if n_p_cov else "B2. no overlap")
for s in samples_p_cov:
    print(f"   P-only-covered: {s[0]} {s[1]}")
print()
print(f"C. leave days: {n_leave} with punch-or-presence: {n_leave_punch} "
      f"({n_leave_punch / n_leave:.1%})" if n_leave else "C. no leave days")
print(f"   by type: {dict(sorted(by_leave.items()))}")
for s in samples_l:
    print(f"   conflict: {s[0]} {s[1]} {s[2]} ({s[3]})")
print()
print(f"D. worked holiday/weekend markers: H/P={n_hp} W/P={n_wp}; half-day rows={n_half}")
