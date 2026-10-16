"""Synthetic single-month workbook for GET /leave/template-sample.

Self-contained (openpyxl only): shows uploaders the exact expected layout
with fake data. The richer test generator lives in scripts/make_leave_fixture.py.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO


def sample_workbook_bytes() -> bytes:
    import openpyxl

    year, month = 2026, 1
    days = [date(year, month, d) for d in range(1, 32)]
    mon = "Jan"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Jan"
    ws.append(["Department", "GBS- ENGINEERING CENTRE,Engineering Centre"])
    ws.append([])
    ws.append(["Start Date", "01-Jan-2026"])
    ws.append(["End Date", "31-Jan-2026"])
    ws.append(["", "", "P", " - Present", "EL", " - Annual Leave"])
    ws.append(["", "", "SL", " - Sick Leave", "W", " - Weekend"])
    ws.append(["Employee Id", "Employee Name"] + [f"{d.day} - {mon}" for d in days])
    demo = [
        ("90001", "Sample User One", {3: "EL", 4: "EL"}),
        ("90002", "Sample User Two", {10: "SL", 11: "0.5SL/0.5P"}),
        ("90003", "Sample User Three", {17: "EL/P"}),
    ]
    for emp_id, name, overrides in demo:
        row = [emp_id, name]
        for d in days:
            if d.day in overrides:
                row.append(overrides[d.day])
            elif d.weekday() >= 5:
                row.append("W")
            else:
                row.append("P")
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
