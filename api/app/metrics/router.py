"""Metrics + roster HTTP endpoints (spec §2/§7). Backend is the single source
of truth for statuses and rates; the frontend only displays these payloads.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core import settings
from app.core.db import get_db
from app.core.deps import viewer
from app.metrics import service
from app.metrics.core import (
    COUNTED_STATUSES,
    build_metrics,
    build_roster,
    roster_csv,
)

router = APIRouter(tags=["metrics"])

VALID_STATUSES = COUNTED_STATUSES | {"no_data", "non_working", "pending"}


def _split(value: str | None):
    if not value:
        return None
    return [t for t in (p.strip() for p in value.split(",")) if t]


@router.get("/dashboard/metrics")
def dashboard_metrics(
    date_from: date = Query(...),
    date_to: date = Query(...),
    teams: str | None = Query(None),
    shift: str | None = Query(None),
    exclude_never_punched: bool = Query(False),
    user=Depends(viewer),
    conn=Depends(get_db),
):
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="date_to is before date_from")
    if (date_to - date_from).days > 400:
        raise HTTPException(status_code=422, detail="range too wide (max 400 days)")

    privileged = (user.get("role") or "").lower() in settings.LEAVE_TYPE_DETAIL_ROLES
    team_filter = service.resolve_team_filter(conn, _split(teams))
    data = service.load_all(conn, date_from, date_to, privileged=privileged)
    wfh_exemptions = {}
    if settings.WFH_EXCLUSION_ENABLED:
        from app.wfh.resolver import exempt_set
        wfh_exemptions = exempt_set(conn, date_from, date_to)
    today = service.today_local()
    shift_filter = shift.strip().lower() if shift and shift.strip() else None

    result = build_metrics(
        employees=data["employees"],
        records=data["records"],
        calendar=data["calendar"],
        leave_dates=data["leave_dates"],
        holidays=data["holidays"],
        coverage_through=data["coverage_through"],
        start=date_from,
        end=date_to,
        today=today,
        team_filter=team_filter,
        shift_filter=shift_filter,
        exclude_never_punched=exclude_never_punched,
        wfh_exemptions=wfh_exemptions,
    )
    result["range"] = {"date_from": date_from.isoformat(),
                       "date_to": date_to.isoformat()}
    result["privileged"] = privileged
    return result


@router.get("/roster")
def get_roster(
    date_: date = Query(..., alias="date"),
    teams: str | None = Query(None),
    shift: str | None = Query(None),
    employee_id: str | None = Query(None),
    status: str | None = Query(None),
    format: str = Query("json"),
    user=Depends(viewer),
    conn=Depends(get_db),
):
    """One row per employee for a single date, with first-last punch
    interval (night shifts ordered by wall-clock start/end)."""
    if format not in ("json", "csv"):
        raise HTTPException(status_code=422, detail="format must be json or csv")

    requested = _split(status)
    if requested:
        bad = [s for s in requested if s not in VALID_STATUSES]
        if bad:
            raise HTTPException(status_code=422,
                                detail=f"unknown status: {', '.join(bad)}")
        statuses = set(requested)
    else:
        statuses = None

    privileged = (user.get("role") or "").lower() in settings.LEAVE_TYPE_DETAIL_ROLES
    day = date_
    team_filter = service.resolve_team_filter(conn, _split(teams))
    data = service.load_all(conn, day, day, privileged=privileged)
    employees = data["employees"]
    if employee_id:
        employees = [e for e in employees if e["id"] == employee_id]
    shift_filter = shift.strip().lower() if shift and shift.strip() else None
    if shift_filter:
        employees = [e for e in employees
                     if (e.get("shift") or "").lower() == shift_filter]

    today = service.today_local()
    roster = build_roster(
        employees=employees,
        records=data["records"],
        calendar=data["calendar"],
        leave_dates=data["leave_dates"],
        holidays=data["holidays"],
        coverage_through=data["coverage_through"],
        d=day,
        today=today,
        team_filter=team_filter,
        statuses=statuses,
    )

    if format == "csv":
        return Response(
            content=roster_csv(roster),
            media_type="text/csv",
            headers={"Content-Disposition":
                     f"attachment; filename=roster-{day.isoformat()}.csv"},
        )

    counts = {s: 0 for s in ("present", "on_leave", "absent", "unverified",
                             "no_data", "non_working", "pending")}
    for r in roster["rows"]:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    roster["counts"] = counts
    roster["total"] = len(roster["rows"])
    return roster
