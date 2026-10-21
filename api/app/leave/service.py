"""Leave-import service: staging, diff, and preview builders.

Sync psycopg2 style, matching the rest of the api. All functions take an
open connection; the router owns commit/rollback. Logs carry ids, counts
and codes only — never names or employee IDs.
"""
from __future__ import annotations

import json
from datetime import date, datetime
import logging
from zoneinfo import ZoneInfo

from psycopg2.extras import execute_values, Json

from app.core import settings
from app.leave.parsing import ParsedImport

log = logging.getLogger(__name__)

NAIROBI = ZoneInfo("Africa/Nairobi")
STAGING_CHUNK = 2000
ISSUE_SAMPLES = 5


def today_nairobi() -> date:
    return datetime.now(NAIROBI).date()


def load_code_map(cur) -> dict:
    cur.execute("SELECT code, kind, leave_group FROM leave_code_map WHERE active")
    return {r["code"]: {"kind": r["kind"], "leave_group": r["leave_group"]}
            for r in cur.fetchall()}


def base_version(cur) -> int:
    cur.execute("SELECT COALESCE(MAX(id), 0) AS v FROM leave_import "
                "WHERE status = 'committed'")
    return cur.fetchone()["v"]


def find_live_import(cur, sha256: str):
    cur.execute("SELECT id, status FROM leave_import WHERE file_sha256 = %s "
                "AND status IN ('parsing','preview_ready','committing','committed')",
                (sha256,))
    return cur.fetchone()


def create_import(cur, *, sha256: str, filename: str, user_id,
                  parsed: ParsedImport) -> int:
    cur.execute(
        """INSERT INTO leave_import
               (file_sha256, original_filename, uploaded_by, status,
                period_start, period_end, coverage_through, department_label,
                base_version, expires_at)
           VALUES (%s,%s,%s,'parsing',%s,%s,%s,%s,%s,
                   now() + interval '24 hours')
           RETURNING id""",
        (sha256, filename, user_id, parsed.period_start, parsed.period_end,
         parsed.coverage_through,
         parsed.sheets[0].department_label if parsed.sheets else None,
         base_version(cur)),
    )
    return cur.fetchone()["id"]


def write_staging(cur, import_id: int, parsed: ParsedImport) -> int:
    values = [(
        import_id, s.name, r.employee_id, r.date, r.raw_code, r.kind,
        r.leave_code, float(r.fraction), r.zoho_presence, r.provisional,
    ) for s in parsed.sheets if not s.blocked for r in s.rows]
    for i in range(0, len(values), STAGING_CHUNK):
        execute_values(cur,
                       """INSERT INTO leave_import_staging
                              (import_id, sheet, employee_id, date, raw_code,
                               kind, leave_code, fraction, zoho_presence, provisional)
                          VALUES %s""",
                       values[i:i + STAGING_CHUNK])
    return len(values)


def _field(issue, name):
    return issue.get(name) if isinstance(issue, dict) else getattr(issue, name)


def aggregate_issues(all_issues: list) -> list[dict]:
    """Collapse repetitive issues to one row with occurrences + samples."""
    grouped: dict[tuple, dict] = {}
    order: list[tuple] = []
    for iss in all_issues:
        severity, code = _field(iss, "severity"), _field(iss, "code")
        sheet, message = _field(iss, "sheet"), _field(iss, "message")
        key = (severity, code, sheet, message)
        row, col = _field(iss, "row"), _field(iss, "col")
        employee_id, day = _field(iss, "employee_id"), _field(iss, "date")
        sample = {"row": row, "col": col, "employee_id": employee_id,
                  "date": str(day) if day else None}
        slot = grouped.get(key)
        if slot is None:
            grouped[key] = {
                "severity": severity, "code": code, "sheet": sheet,
                "row": row, "col": col, "employee_id": employee_id,
                "date": day, "occurrences": 1, "message": message,
                "samples": [sample] if any(sample.values()) else [],
            }
            order.append(key)
        else:
            slot["occurrences"] += 1
            if len(slot["samples"]) < ISSUE_SAMPLES and any(sample.values()):
                slot["samples"].append(sample)
    return [grouped[k] for k in order]


def write_issues(cur, import_id: int, aggregated: list[dict]) -> int:
    values = [(
        import_id, a["severity"], a["code"], a["sheet"], a["row"], a["col"],
        a["employee_id"], a["date"], a["occurrences"], a["message"],
        Json(a["samples"]),
    ) for a in aggregated]
    if values:
        execute_values(cur,
                       """INSERT INTO leave_import_issue
                              (import_id, severity, code, sheet, row, col,
                               employee_id, date, occurrences, message, samples)
                          VALUES %s""",
                       values)
    return len(values)


def _norm_name(name: str | None) -> str:
    return "".join((name or "").lower().split())


def directory_checks(cur, import_id: int, preview_names: dict) -> list[dict]:
    """EMPLOYEE_NOT_IN_SYSTEM + EMPLOYEE_NAME_MISMATCH (IDs only in issues)."""
    cur.execute("SELECT DISTINCT employee_id FROM leave_import_staging "
                "WHERE import_id = %s", (import_id,))
    staged = [r["employee_id"] for r in cur.fetchall()]
    if not staged:
        return []
    cur.execute("SELECT id, name FROM employees WHERE id = ANY(%s)", (staged,))
    directory = {r["id"]: r["name"] for r in cur.fetchall()}
    out = []
    missing = [e for e in staged if e not in directory]
    if missing:
        out.append({
            "severity": "warning", "code": "EMPLOYEE_NOT_IN_SYSTEM",
            "sheet": None, "row": None, "col": None, "employee_id": missing[0],
            "date": None, "occurrences": len(missing),
            "message": f"{len(missing)} IDs not in the employee directory "
                       "(rows stored, apply when they appear)",
            "samples": [{"employee_id": e} for e in missing[:ISSUE_SAMPLES]],
        })
    mismatched = [e for e in staged
                  if e in directory and e in preview_names
                  and _norm_name(directory[e]) != _norm_name(preview_names[e])]
    if mismatched:
        out.append({
            "severity": "warning", "code": "EMPLOYEE_NAME_MISMATCH",
            "sheet": None, "row": None, "col": None, "employee_id": mismatched[0],
            "date": None, "occurrences": len(mismatched),
            "message": f"{len(mismatched)} IDs have a different directory name "
                       "(possible mistyped ID)",
            "samples": [{"employee_id": e} for e in mismatched[:ISSUE_SAMPLES]],
        })
    return out


def diff_counts(cur, import_id: int) -> dict:
    """Set-based diff of staging vs calendar_day (source xls)."""
    cur.execute(
        """SELECT
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE c.employee_id IS NULL) AS new,
               COUNT(*) FILTER (WHERE c.employee_id IS NOT NULL
                                    AND c.raw_code IS DISTINCT FROM s.raw_code) AS changed,
               COUNT(*) FILTER (WHERE c.raw_code IS NOT DISTINCT FROM s.raw_code) AS unchanged,
               COUNT(*) FILTER (WHERE c.employee_id IS NOT NULL
                                    AND c.kind = 'leave' AND s.kind <> 'leave') AS leave_removed,
               COUNT(*) FILTER (WHERE c.employee_id IS NOT NULL
                                    AND c.raw_code IS DISTINCT FROM s.raw_code
                                    AND s.date < CURRENT_DATE) AS past_changed,
               COUNT(DISTINCT s.employee_id) AS employees
           FROM leave_import_staging s
           LEFT JOIN calendar_day c
             ON c.employee_id = s.employee_id AND c.date = s.date AND c.source = 'xls'
           WHERE s.import_id = %s""",
        (import_id,))
    row = cur.fetchone()
    return {k: (row[k] or 0) for k in
            ("total", "new", "changed", "unchanged", "leave_removed",
             "past_changed", "employees")}


def overlap_guard(cur, import_id: int) -> dict | None:
    """D9: >5% of already-stored days in the overlap would change."""
    cur.execute(
        """SELECT COUNT(*) AS stored,
                  COUNT(*) FILTER (WHERE c.raw_code IS DISTINCT FROM s.raw_code) AS changing
           FROM leave_import_staging s
           JOIN calendar_day c
             ON c.employee_id = s.employee_id AND c.date = s.date AND c.source = 'xls'
           WHERE s.import_id = %s""",
        (import_id,))
    row = cur.fetchone()
    stored, changing = row["stored"] or 0, row["changing"] or 0
    if stored and changing / stored > 0.05:
        return {"stored": stored, "changing": changing,
                "ratio": round(changing / stored, 4)}
    return None


def roster_shrank(cur, import_id: int) -> list[str]:
    cur.execute(
        """SELECT c.employee_id FROM
               (SELECT DISTINCT employee_id FROM calendar_day WHERE source = 'xls') c
           WHERE NOT EXISTS (SELECT 1 FROM leave_import_staging s
                             WHERE s.import_id = %s AND s.employee_id = c.employee_id)
           ORDER BY c.employee_id""",
        (import_id,))
    return [r["employee_id"] for r in cur.fetchall()]


def past_changes_sample(cur, import_id: int, limit: int = 20) -> list[dict]:
    cur.execute(
        """SELECT s.employee_id, s.date, c.raw_code AS old_raw, s.raw_code AS new_raw
           FROM leave_import_staging s
           JOIN calendar_day c
             ON c.employee_id = s.employee_id AND c.date = s.date AND c.source = 'xls'
           WHERE s.import_id = %s AND c.raw_code IS DISTINCT FROM s.raw_code
             AND s.date < CURRENT_DATE
           ORDER BY s.date, s.employee_id LIMIT %s""",
        (import_id, limit))
    return [{"employee_id": r["employee_id"], "date": str(r["date"]),
             "old_raw": r["old_raw"], "new_raw": r["new_raw"]}
            for r in cur.fetchall()]


def finalize_preview(cur, import_id: int, parsed: ParsedImport,
                     preview_names: dict) -> dict:
    """Run directory checks, diff, guards; persist issues/counts/summary."""
    issues = list(parsed.issues)
    issues.extend(directory_checks(cur, import_id, preview_names))
    counts = diff_counts(cur, import_id)
    if counts["past_changed"]:
        issues.append({
            "severity": "info", "code": "PAST_DAYS_CHANGED",
            "sheet": None, "row": None, "col": None, "employee_id": None,
            "date": None, "occurrences": counts["past_changed"],
            "message": f"{counts['past_changed']} past days would change",
            "samples": past_changes_sample(cur, import_id),
        })
    if counts["leave_removed"]:
        issues.append({
            "severity": "warning", "code": "LEAVE_REMOVED",
            "sheet": None, "row": None, "col": None, "employee_id": None,
            "date": None, "occurrences": counts["leave_removed"],
            "message": f"{counts['leave_removed']} past leave days would become "
                       "non-leave (possible cancellation)",
            "samples": past_changes_sample(cur, import_id),
        })
    guard = overlap_guard(cur, import_id)
    if guard:
        issues.append({
            "severity": "error", "code": "LARGE_CHANGE",
            "sheet": None, "row": None, "col": None, "employee_id": None,
            "date": None, "occurrences": guard["changing"],
            "message": f"{guard['changing']}/{guard['stored']} stored days "
                       f"({guard['ratio']:.1%}) would change — confirm required",
            "samples": past_changes_sample(cur, import_id, 5),
        })
    shrank = roster_shrank(cur, import_id)
    if shrank:
        issues.append({
            "severity": "info", "code": "ROSTER_SHRANK",
            "sheet": None, "row": None, "col": None,
            "employee_id": shrank[0], "date": None, "occurrences": len(shrank),
            "message": f"{len(shrank)} previously-seen IDs are absent from this file",
            "samples": [{"employee_id": e} for e in shrank[:ISSUE_SAMPLES]],
        })
    cur.execute("SELECT through_date FROM leave_coverage WHERE source = 'xls'")
    cov = cur.fetchone()
    imp_through = parsed.coverage_through
    if cov and imp_through and imp_through < cov["through_date"]:
        issues.append({
            "severity": "warning", "code": "PERIOD_REGRESSION",
            "sheet": None, "row": None, "col": None, "employee_id": None,
            "date": None, "occurrences": 1,
            "message": f"file ends at {imp_through}, before current coverage "
                       f"{cov['through_date']} (allowed; coverage never decreases)",
            "samples": [],
        })

    aggregated = aggregate_issues(issues)
    write_issues(cur, import_id, aggregated)

    sheet_summary = [{
        "sheet": s.name, "blocked": s.blocked,
        "reason": "; ".join(sorted({i.message for i in parsed.issues
                                    if i.sheet == s.name and i.severity == "error"})),
        "start": str(s.start_date) if s.start_date else None,
        "end": str(s.end_date) if s.end_date else None,
        "rows": len(s.rows),
        "employees": len({r.employee_id for r in s.rows}),
    } for s in parsed.sheets]
    counts["sheets"] = len(parsed.sheets)
    cur.execute("UPDATE leave_import SET status = 'preview_ready', counts = %s, "
                "sheet_summary = %s, preview_names = %s WHERE id = %s",
                (Json(counts), Json(sheet_summary), Json(preview_names), import_id))
    log.info("leave import %s: preview ready (%s rows, %s new, %s changed)",
             import_id, counts['total'], counts['new'], counts['changed'])
    return counts


def get_import(cur, import_id: int) -> dict | None:
    cur.execute("SELECT * FROM leave_import WHERE id = %s", (import_id,))
    row = cur.fetchone()
    if row is None:
        return None
    return dict(row)


# --- commit / discard / revert (spec §8) -------------------------------------

COMMIT_LOCK_KEY = 727002


def try_commit_lock(cur) -> bool:
    cur.execute("SELECT pg_try_advisory_xact_lock(%s) AS held", (COMMIT_LOCK_KEY,))
    return bool(cur.fetchone()["held"])


def selected_sheets(cur, import_id: int, requested: list[str] | None) -> list[str]:
    cur.execute("SELECT sheet_summary FROM leave_import WHERE id = %s", (import_id,))
    summary = cur.fetchone()["sheet_summary"] or []
    usable = [s["sheet"] for s in summary if not s["blocked"]]
    if not requested:
        return usable
    unknown = [s for s in requested if s not in {x["sheet"] for x in summary}]
    if unknown:
        raise ValueError(f"unknown sheets: {', '.join(unknown)}")
    blocked = [s for s in requested if s not in usable]
    if blocked:
        raise ValueError(f"blocked sheets cannot be committed: {', '.join(blocked)}")
    return list(requested)


def import_issue_codes(cur, import_id: int, severity: str | None = None) -> set[str]:
    if severity:
        cur.execute("SELECT DISTINCT code FROM leave_import_issue "
                    "WHERE import_id = %s AND severity = %s", (import_id, severity))
    else:
        cur.execute("SELECT DISTINCT code FROM leave_import_issue WHERE import_id = %s",
                    (import_id,))
    return {r["code"] for r in cur.fetchall()}


def overlap_guard_selected(cur, import_id: int, sheets: list[str]) -> dict | None:
    cur.execute(
        """SELECT COUNT(*) AS stored,
                  COUNT(*) FILTER (WHERE c.raw_code IS DISTINCT FROM s.raw_code) AS changing
           FROM leave_import_staging s
           JOIN calendar_day c
             ON c.employee_id = s.employee_id AND c.date = s.date AND c.source = 'xls'
           WHERE s.import_id = %s AND s.sheet = ANY(%s)""",
        (import_id, sheets))
    row = cur.fetchone()
    stored, changing = row["stored"] or 0, row["changing"] or 0
    if stored and changing / stored > 0.05:
        return {"stored": stored, "changing": changing,
                "ratio": round(changing / stored, 4)}
    return None


def commit_import(cur, import_id: int, sheets: list[str],
                  idempotency_key: str | None) -> dict:
    """Run inside one transaction holding the advisory lock + row lock."""
    cur.execute("SELECT * FROM leave_import WHERE id = %s FOR UPDATE", (import_id,))
    imp = cur.fetchone()
    cur.execute("UPDATE leave_import SET status = 'committing' WHERE id = %s",
                (import_id,))
    # Audit every changed day (new rows carry old_raw NULL).
    cur.execute(
        """INSERT INTO calendar_day_change
               (batch_id, employee_id, date, source, old_raw, new_raw)
           SELECT %s, s.employee_id, s.date, 'xls', c.raw_code, s.raw_code
           FROM leave_import_staging s
           LEFT JOIN calendar_day c
             ON c.employee_id = s.employee_id AND c.date = s.date AND c.source = 'xls'
           WHERE s.import_id = %s AND s.sheet = ANY(%s)
             AND c.raw_code IS DISTINCT FROM s.raw_code""",
        (import_id, import_id, sheets))
    audited = cur.rowcount
    # Upsert changed rows only; identical rows are left untouched.
    cur.execute(
        """INSERT INTO calendar_day
               (employee_id, date, source, raw_code, kind, leave_code,
                fraction, zoho_presence, batch_id, updated_at)
           SELECT s.employee_id, s.date, 'xls', s.raw_code, s.kind, s.leave_code,
                  s.fraction, s.zoho_presence, %s, now()
           FROM leave_import_staging s
           WHERE s.import_id = %s AND s.sheet = ANY(%s)
           ON CONFLICT (employee_id, date, source) DO UPDATE SET
               raw_code = EXCLUDED.raw_code, kind = EXCLUDED.kind,
               leave_code = EXCLUDED.leave_code, fraction = EXCLUDED.fraction,
               zoho_presence = EXCLUDED.zoho_presence,
               batch_id = EXCLUDED.batch_id, updated_at = now()
           WHERE calendar_day.raw_code IS DISTINCT FROM EXCLUDED.raw_code""",
        (import_id, import_id, sheets))
    upserted = cur.rowcount
    cur.execute("SELECT MAX(date) AS through FROM leave_import_staging "
                "WHERE import_id = %s AND sheet = ANY(%s)", (import_id, sheets))
    through = cur.fetchone()["through"]
    if through:
        cur.execute(
            """INSERT INTO leave_coverage (source, through_date, batch_id, updated_at)
               VALUES ('xls', %s, %s, now())
               ON CONFLICT (source) DO UPDATE SET
                   through_date = GREATEST(leave_coverage.through_date, EXCLUDED.through_date),
                   batch_id = EXCLUDED.batch_id, updated_at = now()""",
            (through, import_id))
    cur.execute("UPDATE leave_import SET status = 'committed', committed_at = now(), "
                "recompute_status = 'done', idempotency_key = COALESCE(%s, idempotency_key), "
                "preview_names = NULL WHERE id = %s",
                (idempotency_key, import_id))
    # Staging purge (issues stay for history).
    cur.execute("DELETE FROM leave_import_staging WHERE import_id = %s", (import_id,))
    # Verification: every audited change must be visible under this batch or
    # overwritten consistently — recount batch rows vs audited.
    cur.execute("SELECT COUNT(*) AS n FROM calendar_day WHERE batch_id = %s",
                (import_id,))
    batch_rows = cur.fetchone()["n"]
    log.info("leave import %s: committed (%s upserted, %s audited, coverage %s)",
             import_id, upserted, audited, through)
    return {"import_id": import_id, "status": "committed",
            "committed_rows": upserted, "audited": audited,
            "coverage_through": str(through) if through else None,
            "batch_rows": batch_rows}


def discard_import(cur, import_id: int) -> dict:
    cur.execute("SELECT status FROM leave_import WHERE id = %s FOR UPDATE",
                (import_id,))
    row = cur.fetchone()
    if row is None:
        raise LookupError("import not found")
    if row["status"] not in ("preview_ready", "parsing", "failed", "expired"):
        raise ValueError(f"cannot discard import in status {row['status']}")
    cur.execute("DELETE FROM leave_import_staging WHERE import_id = %s", (import_id,))
    cur.execute("UPDATE leave_import SET status = 'discarded', preview_names = NULL "
                "WHERE id = %s", (import_id,))
    log.info("leave import %s: discarded", import_id)
    return {"import_id": import_id, "status": "discarded"}


def latest_committed_id(cur) -> int | None:
    cur.execute("SELECT MAX(id) AS m FROM leave_import WHERE status = 'committed'")
    return cur.fetchone()["m"]


def revert_import(cur, import_id: int, code_map: dict) -> dict:
    """Restore pre-batch values; skip days a later import already overwrote."""
    from app.leave.parsing import derive_day  # noqa: PLC0415 (avoid cycle)

    cur.execute("SELECT status FROM leave_import WHERE id = %s FOR UPDATE",
                (import_id,))
    row = cur.fetchone()
    if row is None:
        raise LookupError("import not found")
    if row["status"] != "committed":
        raise ValueError("only a committed import can be reverted")
    if latest_committed_id(cur) != import_id:
        raise ValueError("only the most recent committed import can be reverted")
    cur.execute("SELECT employee_id, date, source, old_raw, new_raw "
                "FROM calendar_day_change WHERE batch_id = %s ORDER BY date",
                (import_id,))
    changes = cur.fetchall()
    restored = skipped = 0
    for ch in changes:
        cur.execute("SELECT raw_code FROM calendar_day "
                    "WHERE employee_id = %s AND date = %s AND source = %s",
                    (ch["employee_id"], ch["date"], ch["source"]))
        current = cur.fetchone()
        current_raw = current["raw_code"] if current else None
        if current_raw != ch["new_raw"]:
            skipped += 1  # a later import overwrote this day
            continue
        if ch["old_raw"] is None:
            cur.execute("DELETE FROM calendar_day "
                        "WHERE employee_id = %s AND date = %s AND source = %s",
                        (ch["employee_id"], ch["date"], ch["source"]))
        else:
            kind, leave_code, frac, presence, _ = derive_day(ch["old_raw"], code_map)
            cur.execute("UPDATE calendar_day SET raw_code = %s, kind = %s, "
                        "leave_code = %s, fraction = %s, zoho_presence = %s, "
                        "updated_at = now() "
                        "WHERE employee_id = %s AND date = %s AND source = %s",
                        (ch["old_raw"], kind, leave_code, frac, presence,
                         ch["employee_id"], ch["date"], ch["source"]))
        restored += 1
    # Coverage re-derives from the rows that actually remain: with
    # per-sheet commit selection, an import's preview coverage_through can
    # overstate what it committed, so the calendar max is the honest signal.
    cur.execute("SELECT MAX(date) AS m FROM calendar_day WHERE source = 'xls'")
    max_cov = cur.fetchone()["m"]
    if max_cov:
        cur.execute("UPDATE leave_coverage SET through_date = %s, updated_at = now() "
                    "WHERE source = 'xls'", (max_cov,))
        if cur.rowcount == 0:
            cur.execute("INSERT INTO leave_coverage (source, through_date, batch_id)"
                        " VALUES ('xls', %s, %s)", (max_cov, import_id))
    else:
        cur.execute("DELETE FROM leave_coverage WHERE source = 'xls'")
    cur.execute("UPDATE leave_import SET status = 'reverted', reverted_at = now() "
                "WHERE id = %s", (import_id,))
    log.info("leave import %s: reverted (%s restored, %s skipped)",
             import_id, restored, skipped)
    return {"import_id": import_id, "status": "reverted",
            "restored": restored, "skipped": skipped}


# --- types admin + reprocess -------------------------------------------------


def list_types(cur) -> list[dict]:
    cur.execute("SELECT code, label, kind, leave_group, paid, counts_as_present, "
                "aliases, sensitive, active FROM leave_code_map ORDER BY code")
    return [dict(r) for r in cur.fetchall()]


VALID_KINDS = {"working", "weekend", "holiday", "not_employed",
               "leave", "on_duty", "unknown"}


def upsert_type(cur, payload: dict) -> dict:
    from app.leave.parsing import normalize_cell  # noqa: PLC0415 (avoid cycle)

    code = normalize_cell(payload.get("code") or "")
    if not code:
        raise ValueError("code is required")
    kind = payload.get("kind", "unknown")
    if kind not in VALID_KINDS:
        raise ValueError(f"kind must be one of {sorted(VALID_KINDS)}")
    cur.execute(
        """INSERT INTO leave_code_map
               (code, label, kind, leave_group, paid, counts_as_present,
                aliases, sensitive, active)
           VALUES (%s, %s, %s, %s, %s,
                   COALESCE(%s, FALSE), COALESCE(%s, '{}'::text[]), COALESCE(%s, FALSE), TRUE)
           ON CONFLICT (code) DO UPDATE SET
               label = COALESCE(EXCLUDED.label, leave_code_map.label),
               kind = EXCLUDED.kind,
               leave_group = EXCLUDED.leave_group,
               paid = EXCLUDED.paid,
               counts_as_present = EXCLUDED.counts_as_present,
               aliases = EXCLUDED.aliases,
               sensitive = EXCLUDED.sensitive,
               active = TRUE
           RETURNING code""",
        (code, payload.get("label") or code, kind, payload.get("leave_group"),
         payload.get("paid"), payload.get("counts_as_present"),
         payload.get("aliases"), payload.get("sensitive")))
    return {"code": cur.fetchone()["code"]}


def reprocess_calendar(cur) -> dict:
    """Re-derive kind/leave_code/fraction/zoho_presence from raw_code (D2)."""
    from app.leave.parsing import derive_day  # noqa: PLC0415 (avoid cycle)

    code_map = load_code_map(cur)
    cur.execute("SELECT employee_id, date, source, raw_code, kind, leave_code, "
                "fraction, zoho_presence FROM calendar_day")
    rows = cur.fetchall()
    updated = 0
    for r in rows:
        kind, leave_code, frac, presence, _ = derive_day(r["raw_code"] or "", code_map)
        if (r["kind"], r["leave_code"], float(r["fraction"]),
                r["zoho_presence"]) != (kind, leave_code, frac, presence):
            cur.execute("UPDATE calendar_day SET kind = %s, leave_code = %s, "
                        "fraction = %s, zoho_presence = %s, updated_at = now() "
                        "WHERE employee_id = %s AND date = %s AND source = %s",
                        (kind, leave_code, frac, presence,
                         r["employee_id"], r["date"], r["source"]))
            updated += 1
    log.info("leave reprocess: %s/%s calendar rows updated", updated, len(rows))
    return {"scanned": len(rows), "updated": updated}
