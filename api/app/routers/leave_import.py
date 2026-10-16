"""Leave-import preview API: upload, preview, issues, changes, history.

All endpoints admin only. Parsing runs synchronously inside POST
(no background-job infra in this repo; a 10 MB workbook parses in
seconds) — the status/polling shapes are kept so a worker can drop in
later. Upload bytes are never persisted: staging rows + aggregated issues
are the preview (names live only in the preview_names blob, purged on
commit/discard/expiry). Logs carry ids, counts and codes only.
"""
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

from app.core import settings
from app.core.db import get_conn, get_db
from app.core.deps import admin, viewer
from app.leave import service
from app.leave.janitor import run_janitor
from app.leave.parsing import (
    FileTooLargeError,
    FileTypeUnsupportedError,
    FileUnreadableError,
    parse_leave_workbook,
)
from app.leave.sample import sample_workbook_bytes
from app.routers.schemas import LeaveCommitIn, LeaveTypeIn

router = APIRouter(prefix="/leave", tags=["leave"])

ALLOWED_EXTENSIONS = (".xls", ".xlsx")


def _payload(imp: dict) -> dict:
    return {
        "import_id": imp["id"],
        "status": imp["status"],
        "original_filename": imp["original_filename"],
        "uploaded_at": str(imp["uploaded_at"]) if imp["uploaded_at"] else None,
        "period_start": str(imp["period_start"]) if imp["period_start"] else None,
        "period_end": str(imp["period_end"]) if imp["period_end"] else None,
        "coverage_through": str(imp["coverage_through"]) if imp["coverage_through"] else None,
        "department_label": imp["department_label"],
        "counts": imp["counts"],
        "sheets": imp["sheet_summary"],
        "base_version": imp["base_version"],
        "committed_at": str(imp["committed_at"]) if imp["committed_at"] else None,
        "reverted_at": str(imp["reverted_at"]) if imp["reverted_at"] else None,
        "recompute_status": imp["recompute_status"],
        "preview_names": imp.get("preview_names") or {},
    }


def _mark_failed(import_id: int | None, error_id: str, note: str) -> None:
    if import_id is None:
        return
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE leave_import SET status = 'failed', error_id = %s "
                    "WHERE id = %s", (f"{error_id}: {note}", import_id))
        conn.commit()
        cur.close()
    finally:
        conn.close()


@router.post("/imports")
def upload_leave(file: UploadFile = File(...), user=Depends(admin),
                 conn=Depends(get_db)):
    import psycopg2.errors  # noqa: PLC0415 (error type only)

    filename = (file.filename or "").strip()
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=415,
                            detail="wrong file type: expected .xls or .xlsx")
    data = file.file.read()
    max_bytes = settings.LEAVE_UPLOAD_MAX_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=413,
                            detail=f"file too large: {len(data)} bytes "
                                   f"(max {settings.LEAVE_UPLOAD_MAX_MB} MB)")
    sha256 = __import__("hashlib").sha256(data).hexdigest()

    try:
        cur = conn.cursor()
        run_janitor(conn)
        dup = service.find_live_import(cur, sha256)
        if dup:
            cur.close()
            return {"import_id": dup["id"], "status": dup["status"],
                    "already_imported": True}
        try:
            parsed = parse_leave_workbook(
                data, service.load_code_map(cur),
                set(settings.EXPECTED_DEPARTMENT_LABELS))
        except FileTypeUnsupportedError as exc:
            raise HTTPException(status_code=415, detail=f"wrong file type: {exc}")
        except FileUnreadableError as exc:
            raise HTTPException(status_code=422, detail=f"file unreadable: {exc}")
        except FileTooLargeError:
            raise HTTPException(status_code=413, detail="file too large")

        import_id = service.create_import(
            cur, sha256=sha256, filename=filename,
            user_id=user.get("id"), parsed=parsed)
        try:
            service.write_staging(cur, import_id, parsed)
            preview_names: dict[str, str] = {}
            for s in parsed.sheets:
                preview_names.update(s.names)
            counts = service.finalize_preview(cur, import_id, parsed, preview_names)
        except Exception:
            conn.rollback()
            raise
        conn.commit()
        imp = service.get_import(cur, import_id)
        cur.close()
    except HTTPException:
        conn.rollback()
        raise
    except psycopg2.errors.UniqueViolation:
        # Concurrent duplicate upload: the winner's row is the preview.
        conn.rollback()
        conn2 = get_conn()
        try:
            cur2 = conn2.cursor()
            dup = service.find_live_import(cur2, sha256)
            cur2.close()
        finally:
            conn2.close()
        if dup:
            return {"import_id": dup["id"], "status": dup["status"],
                    "already_imported": True}
        error_id = uuid.uuid4().hex[:8]
        print(f"leave import conflict: error_id={error_id} sha={sha256[:12]}")
        raise HTTPException(status_code=409, detail="conflicting upload; "
                            "re-run the preview")
    except Exception as exc:  # noqa: BLE001 — mapped to 500 + error_id, never a trace
        conn.rollback()
        error_id = uuid.uuid4().hex[:8]
        print(f"leave import failed: error_id={error_id} "
              f"bytes={len(data)} sha={sha256[:12]} ({type(exc).__name__})")
        raise HTTPException(status_code=500,
                            detail=f"import failed and nothing was saved "
                                   f"(error_id={error_id}); try again")
    payload = _payload(imp)
    payload.update({"already_imported": False, "counts": counts})
    return payload


@router.get("/imports/{import_id}")
def get_import(import_id: int, user=Depends(admin), conn=Depends(get_db)):
    cur = conn.cursor()
    imp = service.get_import(cur, import_id)
    cur.close()
    if imp is None:
        raise HTTPException(status_code=404, detail="import not found")
    return _payload(imp)


@router.get("/imports/{import_id}/issues")
def list_issues(import_id: int, severity: str | None = Query(None),
                code: str | None = Query(None), sheet: str | None = Query(None),
                limit: int = Query(100, ge=1, le=1000),
                offset: int = Query(0, ge=0), user=Depends(admin),
                conn=Depends(get_db)):
    cur = conn.cursor()
    if service.get_import(cur, import_id) is None:
        cur.close()
        raise HTTPException(status_code=404, detail="import not found")
    clauses, params = ["import_id = %s"], [import_id]
    if severity:
        clauses.append("severity = %s")
        params.append(severity)
    if code:
        clauses.append("code = %s")
        params.append(code)
    if sheet:
        clauses.append("sheet = %s")
        params.append(sheet)
    where = "WHERE " + " AND ".join(clauses)
    cur.execute(f"SELECT COUNT(*) AS n FROM leave_import_issue {where}", params)
    total = cur.fetchone()["n"]
    cur.execute(
        f"""SELECT id, severity, code, sheet, row, col, employee_id, date,
                   occurrences, message, samples
            FROM leave_import_issue {where}
            ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1
                     ELSE 2 END, code, sheet NULLS LAST, id
            LIMIT %s OFFSET %s""",
        [*params, limit, offset])
    rows = [dict(r, date=str(r["date"]) if r["date"] else None)
            for r in cur.fetchall()]
    cur.close()
    return {"total": total, "limit": limit, "offset": offset, "issues": rows}


@router.get("/imports/{import_id}/changes")
def list_changes(import_id: int, type: str | None = Query(None),
                 limit: int = Query(100, ge=1, le=1000),
                 offset: int = Query(0, ge=0), user=Depends(admin),
                 conn=Depends(get_db)):
    if type is not None and type not in ("new", "changed", "leave_removed"):
        raise HTTPException(status_code=400,
                            detail="type must be new, changed or leave_removed")
    cur = conn.cursor()
    if service.get_import(cur, import_id) is None:
        cur.close()
        raise HTTPException(status_code=404, detail="import not found")
    base = ("FROM leave_import_staging s LEFT JOIN calendar_day c "
            "ON c.employee_id = s.employee_id AND c.date = s.date "
            "AND c.source = 'xls' WHERE s.import_id = %s")
    extra, params = "", [import_id]
    if type == "new":
        extra = " AND c.employee_id IS NULL"
    elif type == "changed":
        extra = (" AND c.employee_id IS NOT NULL"
                 " AND c.raw_code IS DISTINCT FROM s.raw_code")
    elif type == "leave_removed":
        extra = " AND c.kind = 'leave' AND s.kind <> 'leave'"
    cur.execute(f"SELECT COUNT(*) AS n {base}{extra}", params)
    total = cur.fetchone()["n"]
    cur.execute(
        f"""SELECT s.employee_id, s.date, s.raw_code AS new_raw, s.kind AS new_kind,
                   c.raw_code AS old_raw, c.kind AS old_kind,
                   CASE WHEN c.employee_id IS NULL THEN 'new'
                        WHEN c.kind = 'leave' AND s.kind <> 'leave'
                        THEN 'leave_removed'
                        WHEN c.raw_code IS DISTINCT FROM s.raw_code THEN 'changed'
                        ELSE 'unchanged' END AS change_type
            {base}{extra} ORDER BY s.date, s.employee_id LIMIT %s OFFSET %s""",
        [*params, limit, offset])
    rows = [dict(r, date=str(r["date"])) for r in cur.fetchall()]
    cur.close()
    return {"total": total, "limit": limit, "offset": offset, "changes": rows}


@router.get("/imports")
def list_imports(limit: int = Query(50, ge=1, le=200), user=Depends(admin),
                 conn=Depends(get_db)):
    cur = conn.cursor()
    cur.execute(
        """SELECT i.id, i.status, i.original_filename, u.email AS uploaded_by,
                  i.uploaded_at, i.period_start, i.period_end,
                  i.coverage_through, i.counts, i.committed_at, i.reverted_at
           FROM leave_import i LEFT JOIN users u ON u.id = i.uploaded_by
           ORDER BY i.id DESC LIMIT %s""",
        (limit,))
    rows = [dict(r,
                 uploaded_at=str(r["uploaded_at"]) if r["uploaded_at"] else None,
                 period_start=str(r["period_start"]) if r["period_start"] else None,
                 period_end=str(r["period_end"]) if r["period_end"] else None,
                 coverage_through=str(r["coverage_through"])
                 if r["coverage_through"] else None,
                 committed_at=str(r["committed_at"]) if r["committed_at"] else None,
                 reverted_at=str(r["reverted_at"]) if r["reverted_at"] else None)
            for r in cur.fetchall()]
    cur.close()
    return rows


@router.get("/coverage")
def get_coverage(user=Depends(admin), conn=Depends(get_db)):
    cur = conn.cursor()
    cur.execute("SELECT source, through_date, batch_id, updated_at FROM leave_coverage")
    sources = {r["source"]: {
        "through_date": str(r["through_date"]),
        "batch_id": r["batch_id"],
        "updated_at": str(r["updated_at"]),
    } for r in cur.fetchall()}
    cur.execute("SELECT MAX(committed_at) AS last FROM leave_import "
                "WHERE status = 'committed'")
    last = cur.fetchone()["last"]
    cur.close()
    primary = sources.get("xls") or sources.get("api")
    return {
        "through_date": primary["through_date"] if primary else None,
        "last_import_at": str(last) if last else None,
        "source": "xls" if "xls" in sources else ("api" if sources else None),
        "sources": sources,
    }


@router.get("/template-sample")
def template_sample(user=Depends(admin)):
    data = sample_workbook_bytes()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 "attachment; filename=leave-template-sample.xlsx"},
    )


def _committed_summary(imp: dict) -> dict:
    return {
        "import_id": imp["id"], "status": imp["status"],
        "committed_at": str(imp["committed_at"]) if imp["committed_at"] else None,
        "coverage_through": str(imp["coverage_through"])
        if imp["coverage_through"] else None,
        "counts": imp["counts"],
    }


@router.post("/imports/{import_id}/commit")
def commit_import(import_id: int, payload: LeaveCommitIn, user=Depends(admin),
                 conn=Depends(get_db)):
    import psycopg2.errors  # noqa: PLC0415 (error type only)

    try:
        cur = conn.cursor()
        if not service.try_commit_lock(cur):
            conn.rollback()
            raise HTTPException(status_code=409, detail="another commit holds "
                                "the lock (IMPORT_IN_PROGRESS)")
        imp = service.get_import(cur, import_id)
        if imp is None:
            conn.rollback()
            raise HTTPException(status_code=404, detail="import not found")
        key = (payload.idempotency_key or "").strip() or None
        if imp["status"] == "committed":
            if key and imp.get("idempotency_key") == key:
                conn.rollback()
                return _committed_summary(imp)
            conn.rollback()
            raise HTTPException(status_code=422,
                                detail="import is already committed")
        if key:
            cur.execute("SELECT * FROM leave_import WHERE idempotency_key = %s "
                        "AND status = 'committed' AND id <> %s", (key, import_id))
            replay = cur.fetchone()
            if replay:
                conn.rollback()
                return _committed_summary(dict(replay))
        if imp["status"] != "preview_ready":
            conn.rollback()
            raise HTTPException(status_code=422,
                                detail=f"import is {imp['status']}, not preview_ready")
        if imp["expires_at"] and imp["expires_at"] < datetime.now(timezone.utc):
            cur.execute("UPDATE leave_import SET status = 'expired' WHERE id = %s",
                        (import_id,))
            conn.commit()
            raise HTTPException(status_code=422,
                                detail="preview expired; re-upload the file")
        if imp["base_version"] != service.base_version(cur):
            conn.rollback()
            raise HTTPException(status_code=409, detail="another commit landed "
                                "after this preview (BASE_VERSION_STALE); "
                                "re-run the preview")
        try:
            sheets = service.selected_sheets(cur, import_id, payload.sheets)
        except ValueError as exc:
            conn.rollback()
            raise HTTPException(status_code=422, detail=str(exc))
        codes = service.import_issue_codes(cur, import_id)
        if "LARGE_CHANGE" in codes and not payload.confirm_large_change:
            conn.rollback()
            raise HTTPException(status_code=422, detail="this import would change "
                                "an unusually large share of stored days "
                                "(LARGE_CHANGE); tick 'I expect this many changes'")
        if "DEPARTMENT_MISMATCH" in codes and not payload.acknowledge_department:
            conn.rollback()
            raise HTTPException(status_code=422, detail="department label is "
                                "unexpected (DEPARTMENT_MISMATCH); tick to acknowledge")
        # Re-check the D9 guard against the selected sheets only.
        guard = service.overlap_guard_selected(cur, import_id, sheets)
        if guard and not payload.confirm_large_change:
            conn.rollback()
            raise HTTPException(status_code=422, detail="this selection would change "
                                f"{guard['changing']}/{guard['stored']} stored days; "
                                "tick 'I expect this many changes'")
        try:
            result = service.commit_import(cur, import_id, sheets, key)
        except psycopg2.errors.UniqueViolation:
            # Idempotency-key race: another request committed first.
            conn.rollback()
            conn2 = get_conn()
            try:
                cur2 = conn2.cursor()
                cur2.execute("SELECT * FROM leave_import "
                             "WHERE idempotency_key = %s AND status = 'committed'",
                             (key,))
                replay = cur2.fetchone()
                cur2.close()
            finally:
                conn2.close()
            if replay:
                return _committed_summary(dict(replay))
            raise HTTPException(status_code=409, detail="conflicting commit; "
                                "re-run the preview")
        conn.commit()
        cur.close()
        return result
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — 500 + error_id, never a trace
        conn.rollback()
        error_id = uuid.uuid4().hex[:8]
        print(f"leave commit {import_id} failed: error_id={error_id} "
              f"({type(exc).__name__})")
        raise HTTPException(status_code=500,
                            detail=f"commit failed and nothing was saved "
                                   f"(error_id={error_id}); retry is safe")


@router.post("/imports/{import_id}/discard")
def discard_import(import_id: int, user=Depends(admin), conn=Depends(get_db)):
    cur = conn.cursor()
    try:
        result = service.discard_import(cur, import_id)
    except LookupError:
        conn.rollback()
        raise HTTPException(status_code=404, detail="import not found")
    except ValueError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    conn.commit()
    cur.close()
    return result


@router.post("/imports/{import_id}/revert")
def revert_import(import_id: int, user=Depends(admin), conn=Depends(get_db)):
    cur = conn.cursor()
    if not service.try_commit_lock(cur):
        conn.rollback()
        raise HTTPException(status_code=409, detail="another commit holds "
                            "the lock (IMPORT_IN_PROGRESS)")
    try:
        result = service.revert_import(
            cur, import_id, service.load_code_map(cur))
    except LookupError:
        conn.rollback()
        raise HTTPException(status_code=404, detail="import not found")
    except ValueError as exc:
        conn.rollback()
        # "Only the most recent committed import" is a state conflict.
        status = 409 if "most recent" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — 500 + error_id, never a trace
        conn.rollback()
        error_id = uuid.uuid4().hex[:8]
        print(f"leave revert {import_id} failed: error_id={error_id} "
              f"({type(exc).__name__})")
        raise HTTPException(status_code=500,
                            detail=f"revert failed and nothing was saved "
                                   f"(error_id={error_id})")
    conn.commit()
    cur.close()
    return result


@router.get("/calendar")
def get_calendar(
    employee_id: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(5000, ge=1, le=20000),
    offset: int = Query(0, ge=0),
    user=Depends(viewer),
    conn=Depends(get_db),
):
    """Flat per-day calendar rows for the attendance overlay (spec §9).

    One row per (employee, date): when both `xls` and `api` sources exist,
    LEAVE_SOURCE_PRIORITY decides. `leave_type` is role-gated (D12): roles
    in LEAVE_TYPE_DETAIL_ROLES see the mapped label, everyone else sees
    'On leave' (null when the day is not leave).
    """
    privileged = user.get("role") in settings.LEAVE_TYPE_DETAIL_ROLES
    priority = [s for s in settings.LEAVE_SOURCE_PRIORITY if s in ("api", "xls")]
    for s in ("api", "xls"):
        if s not in priority:
            priority.append(s)
    case = " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(priority))
    clauses, params = [], []
    if employee_id:
        clauses.append("c.employee_id = %s")
        params.append(employee_id)
    if date_from:
        clauses.append("c.date >= %s")
        params.append(date_from)
    if date_to:
        clauses.append("c.date <= %s")
        params.append(date_to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = conn.cursor()
    cur.execute(
        f"""SELECT COUNT(*) AS n FROM (
                SELECT DISTINCT ON (c.employee_id, c.date) c.employee_id
                FROM calendar_day c {where}
            ) d""",
        params)
    total = cur.fetchone()["n"]
    cur.execute(
        f"""SELECT d.employee_id, d.date, d.source, d.raw_code, d.kind,
                   d.leave_code, d.fraction, d.zoho_presence, m.label
            FROM (
                SELECT DISTINCT ON (c.employee_id, c.date)
                    c.employee_id, c.date, c.source, c.raw_code, c.kind,
                    c.leave_code, c.fraction, c.zoho_presence
                FROM calendar_day c {where}
                ORDER BY c.employee_id, c.date, CASE c.source {case} ELSE 99 END
            ) d LEFT JOIN leave_code_map m ON m.code = d.leave_code
            ORDER BY d.date DESC, d.employee_id
            LIMIT %s OFFSET %s""",
        [*params, limit, offset])
    rows = []
    for r in cur.fetchall():
        if r["kind"] != "leave":
            leave_type = None
        elif privileged:
            leave_type = r["label"] or r["leave_code"] or "On leave"
        else:
            leave_type = "On leave"
        rows.append({
            "employee_id": r["employee_id"], "date": str(r["date"]),
            "source": r["source"], "raw_code": r["raw_code"],
            "day_kind": r["kind"], "leave_type": leave_type,
            "leave_fraction": float(r["fraction"]),
            "zoho_presence": r["zoho_presence"],
        })
    cur.close()
    return {"total": total, "limit": limit, "offset": offset, "days": rows}


@router.get("/types")
def list_types(user=Depends(admin), conn=Depends(get_db)):
    cur = conn.cursor()
    rows = service.list_types(cur)
    cur.close()
    return rows


@router.put("/types")
def put_type(payload: LeaveTypeIn, user=Depends(admin), conn=Depends(get_db)):
    cur = conn.cursor()
    try:
        result = service.upsert_type(cur, payload.model_dump())
    except ValueError as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    conn.commit()
    cur.close()
    return result


@router.post("/reprocess")
def reprocess(user=Depends(admin), conn=Depends(get_db)):
    cur = conn.cursor()
    try:
        result = service.reprocess_calendar(cur)
        conn.commit()
        cur.close()
        return result
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        error_id = uuid.uuid4().hex[:8]
        print(f"leave reprocess failed: error_id={error_id} ({type(exc).__name__})")
        raise HTTPException(status_code=500,
                            detail=f"reprocess failed (error_id={error_id})")
