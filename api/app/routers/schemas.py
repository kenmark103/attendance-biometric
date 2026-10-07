"""Shared request/response models for the domain routers."""
from datetime import date
from typing import List, Optional

from pydantic import BaseModel


class AttendanceRecordIn(BaseModel):
    employee_id: str
    employee_name: str
    date: date
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    work_hours: float = 0
    overtime_hours: float = 0
    late_in: bool = False
    early_out: bool = False
    present: bool = False
    team_name: str


class BulkAttendanceIn(BaseModel):
    source: str
    records: List[AttendanceRecordIn]


class LeaveRecordIn(BaseModel):
    employee_id: str
    date: date
    leave_type: str
    status: str = "approved"


class BulkLeaveIn(BaseModel):
    source: str = "zoho"
    records: List[LeaveRecordIn]


class AttendanceTeamUpdate(BaseModel):
    employee_id: str
    date: date
    team_name: str | None = None


class BulkAttendanceTeamUpdateIn(BaseModel):
    records: list[AttendanceTeamUpdate]


class WfhIn(BaseModel):
    employee_id: str
    date: date
    reason: Optional[str] = None
