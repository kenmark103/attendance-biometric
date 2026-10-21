"""Bulk attendance and leave write endpoints."""
from fastapi import APIRouter, Depends, HTTPException

from app.attendance import service
from app.core.db import get_db
from app.core.deps import admin
from app.routers.schemas import (
    BulkAttendanceIn,
    BulkAttendanceOut,
    BulkAttendanceTeamUpdateIn,
    BulkAttendanceTeamUpdateOut,
    BulkLeaveIn,
    BulkLeaveOut,
)

router = APIRouter(tags=["attendance"])


@router.post("/attendance/bulk", response_model=BulkAttendanceOut)
def bulk_insert_attendance(payload: BulkAttendanceIn, user=Depends(admin),
                           conn=Depends(get_db)):
    if payload.source not in service.ALLOWED_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"source must be one of {sorted(service.ALLOWED_SOURCES)}",
        )
    return service.insert_attendance(conn, payload)


@router.post("/leave/bulk", response_model=BulkLeaveOut)
def bulk_insert_leave(payload: BulkLeaveIn, user=Depends(admin),
                      conn=Depends(get_db)):
    return service.insert_leave(conn, payload)


@router.post("/attendance/bulk/team", response_model=BulkAttendanceTeamUpdateOut)
def update_attendance_teams(payload: BulkAttendanceTeamUpdateIn,
                            user=Depends(admin), conn=Depends(get_db)):
    return service.update_attendance_teams(conn, payload)
