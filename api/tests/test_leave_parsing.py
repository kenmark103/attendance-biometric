"""Leave-workbook parser tests. Pure unit tests — no DB, no PII.

Run: docker compose exec api pytest tests/test_leave_parsing.py -v
Fixtures are synthetic (scripts/make_leave_fixture.py), written to tmp_path.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from app.leave.parsing import (
    FileTooLargeError,
    FileTypeUnsupportedError,
    derive_day,
    match_key,
    normalize_employee_id,
    parse_leave_workbook,
)

openpyxl = pytest.importorskip("openpyxl")

import make_leave_fixture as fix  # noqa: E402


def _need_xlwt():
    return pytest.importorskip("xlwt")

CODE_MAP = {
    "P": {"kind": "working", "leave_group": None},
    "A": {"kind": "working", "leave_group": None},
    "W": {"kind": "weekend", "leave_group": None},
    "H": {"kind": "holiday", "leave_group": None},
    "-": {"kind": "not_employed", "leave_group": None},
    "EL": {"kind": "leave", "leave_group": "annual"},
    "SL": {"kind": "leave", "leave_group": "sick"},
    "ML": {"kind": "leave", "leave_group": "maternity"},
    "PL": {"kind": "leave", "leave_group": "paternity"},
    "L": {"kind": "leave", "leave_group": "unpaid"},
    "OD": {"kind": "on_duty", "leave_group": None},
    "SL1": {"kind": "leave", "leave_group": "sick"},
    "AL": {"kind": "leave", "leave_group": "annual"},
}

DEPT = {fix.DEPT}


def _grid_bytes(grid, fmt):
    import io

    if fmt == "xlsx":
        wb = openpyxl.Workbook()
        ws = wb.active
        for row in grid:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    if fmt == "xls":
        _need_xlwt()
        import xlwt as _xlwt

        book = _xlwt.Workbook()
        ws = book.add_sheet("M1")
        for r, row in enumerate(grid):
            for c, val in enumerate(row):
                ws.write(r, c, "" if val is None else val)
        buf = io.BytesIO()
        book.save(buf)
        return buf.getvalue()
    raise AssertionError(fmt)


def _jan_grid(**kw):
    return fix.build_grid(2026, 1, 4, set(), 0, **kw)


def _codes(issue_list, code):
    return [i for i in issue_list if i.code == code]


# --- code grammar ------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("P", ("working", None, 1.0, True, None)),
    ("A", ("working", None, 1.0, False, None)),
    ("W", ("weekend", None, 1.0, None, None)),
    ("H", ("holiday", None, 1.0, None, None)),
    ("-", ("not_employed", None, 1.0, None, None)),
    ("EL", ("leave", "EL", 1.0, None, None)),
    ("SL", ("leave", "SL", 1.0, None, None)),
    ("OD", ("on_duty", None, 1.0, None, None)),
    ("EL/P", ("leave", "EL", 1.0, True, None)),
    ("SL/P", ("leave", "SL", 1.0, True, None)),
    ("H/P", ("holiday", None, 1.0, True, None)),
    ("W/P", ("weekend", None, 1.0, True, None)),
    ("OD/P", ("on_duty", None, 1.0, True, None)),
    ("L/P", ("leave", "L", 1.0, True, None)),
    ("0.5EL/0.5P", ("leave", "EL", 0.5, True, None)),
    ("0.5SL/0.5P", ("leave", "SL", 0.5, True, None)),
    ("0.5EL/0.5A", ("leave", "EL", 0.5, False, None)),
    ("0.5L/0.5A", ("leave", "L", 0.5, False, None)),
    ("", ("unknown", None, 1.0, None, "CELL_EMPTY")),
    ("CL", ("unknown", None, 1.0, None, "CELL_UNKNOWN_CODE")),
    ("EL/P/X", ("unknown", None, 1.0, None, "CELL_CODE_UNPARSEABLE")),
    ("EL/EL", ("unknown", None, 1.0, None, "CELL_CODE_UNPARSEABLE")),
    ("???", ("unknown", None, 1.0, None, "CELL_CODE_UNPARSEABLE")),
])
def test_derive_day(raw, expected):
    assert derive_day(raw, CODE_MAP) == expected


def test_derive_day_lowercase_whitespace_normalised():
    # derive_day takes normalised input; the workbook path normalises first.
    from app.leave.parsing import normalize_cell
    assert normalize_cell(" el/p ") == "EL/P"
    assert normalize_cell("0.5 el / 0.5 p") == "0.5EL/0.5P"


# --- ID normalisation (D3) ---------------------------------------------------


@pytest.mark.parametrize("value,expected", [
    (90001.0, "90001"),
    (" 90001 ", "90001"),
    ("90 001", "90001"),
    ("00123", "00123"),
    (None, None),
    ("", None),
    ("   ", None),
    (12.5, None),
    (True, None),
])
def test_normalize_employee_id(value, expected):
    assert normalize_employee_id(value) == expected


def test_match_key_strips_leading_zeros():
    assert match_key("00123") == "123"
    assert match_key("90001") == "90001"


# --- sheet location / validation ---------------------------------------------


@pytest.mark.parametrize("fmt", ["xlsx", "xls"])
def test_basic_sheet_parses(fmt):
    res = parse_leave_workbook(_grid_bytes(_jan_grid(), fmt), CODE_MAP, DEPT)
    assert len(res.sheets) == 1 and not res.sheets[0].blocked
    assert res.sheets[0].start_date == date(2026, 1, 1)
    assert res.sheets[0].end_date == date(2026, 1, 31)
    assert len(res.sheets[0].rows) == 4 * 31
    assert res.period_start == date(2026, 1, 1)
    assert res.coverage_through == date(2026, 1, 31)


def test_missing_a1_label_still_parses():
    res = parse_leave_workbook(_grid_bytes(_jan_grid(missing_a1=True), "xlsx"),
                               CODE_MAP, DEPT)
    assert not res.sheets[0].blocked
    assert len(res.sheets[0].rows) == 4 * 31


def test_html_disguised_xls():
    grid = _jan_grid()
    cells = "".join(
        "<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>" for row in grid)
    data = f"<html><body><table>{cells}</table></body></html>".encode()
    res = parse_leave_workbook(data, CODE_MAP, DEPT)
    assert not res.sheets[0].blocked
    assert len(res.sheets[0].rows) == 4 * 31


def test_unsupported_type_and_too_large():
    with pytest.raises(FileTypeUnsupportedError):
        parse_leave_workbook(b"%PDF-1.4 nope", CODE_MAP, DEPT)
    with pytest.raises(FileTooLargeError):
        parse_leave_workbook(b"P" * (10 * 1024 * 1024 + 1), CODE_MAP, DEPT)


def test_no_header_sheet_skipped():
    grid = [["a", "b"], ["c", "d"]]
    res = parse_leave_workbook(_grid_bytes(grid, "xlsx"), CODE_MAP, DEPT)
    assert res.sheets[0].blocked
    assert _codes(res.issues, "SHEET_SKIPPED_NO_HEADER")
    assert _codes(res.issues, "NO_VALID_SHEETS")


def test_bad_dates_block_sheet():
    grid = _jan_grid()
    grid[2][1] = "not-a-date"
    res = parse_leave_workbook(_grid_bytes(grid, "xlsx"), CODE_MAP, DEPT)
    assert res.sheets[0].blocked
    assert _codes(res.issues, "SHEET_DATES_INVALID")


def test_end_before_start_block_sheet():
    grid = _jan_grid()
    grid[2][1], grid[3][1] = "31-Jan-2026", "01-Jan-2026"
    res = parse_leave_workbook(_grid_bytes(grid, "xlsx"), CODE_MAP, DEPT)
    assert _codes(res.issues, "SHEET_DATES_INVALID")


def test_header_mismatch_blocks_sheet():
    grid = _jan_grid()
    grid[6] = grid[6][:10]  # truncate day columns
    res = parse_leave_workbook(_grid_bytes(grid, "xlsx"), CODE_MAP, DEPT)
    assert res.sheets[0].blocked
    assert _codes(res.issues, "SHEET_HEADER_MISMATCH")


def test_period_overlap_blocks_later_sheet():
    import io
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "JanA"
    for row in _jan_grid():
        ws1.append(row)
    ws2 = wb.create_sheet("JanB")
    for row in _jan_grid():
        ws2.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    res = parse_leave_workbook(buf.getvalue(), CODE_MAP, DEPT)
    assert not res.sheets[0].blocked
    assert res.sheets[1].blocked
    assert _codes(res.issues, "SHEET_PERIOD_OVERLAP")


def test_department_mismatch_warns_only():
    grid = _jan_grid()
    grid[0][1] = "SOME OTHER DEPT"
    res = parse_leave_workbook(_grid_bytes(grid, "xlsx"), CODE_MAP, DEPT)
    assert not res.sheets[0].blocked
    assert _codes(res.issues, "DEPARTMENT_MISMATCH")


# --- rows --------------------------------------------------------------------


def test_row_id_missing_and_invalid():
    grid = _jan_grid()
    grid[7][0] = ""
    grid[8][0] = 12.5
    res = parse_leave_workbook(_grid_bytes(grid, "xlsx"), CODE_MAP, DEPT)
    assert _codes(res.issues, "ROW_ID_MISSING")
    assert _codes(res.issues, "ROW_ID_INVALID")
    # 2 bad rows of 4 = 50% > 5% -> blocked
    assert _codes(res.issues, "TOO_MANY_ROW_ERRORS")
    assert res.sheets[0].blocked


def test_blank_rows_skipped_not_stopping():
    grid = _jan_grid()
    grid.insert(8, [])
    res = parse_leave_workbook(_grid_bytes(grid, "xlsx"), CODE_MAP, DEPT)
    assert not res.sheets[0].blocked
    assert len(res.sheets[0].rows) == 4 * 31


def test_duplicate_identical_deduped():
    grid = _jan_grid()
    grid.append(list(grid[7]))
    res = parse_leave_workbook(_grid_bytes(grid, "xlsx"), CODE_MAP, DEPT)
    assert not res.sheets[0].blocked
    assert _codes(res.issues, "ROW_DUPLICATE_IDENTICAL")
    assert len(res.sheets[0].rows) == 4 * 31


def test_duplicate_conflict_blocks():
    grid = _jan_grid()
    dup = list(grid[7])
    dup[-1] = "EL"
    grid.append(dup)
    res = parse_leave_workbook(_grid_bytes(grid, "xlsx"), CODE_MAP, DEPT)
    assert res.sheets[0].blocked
    assert _codes(res.issues, "ROW_DUPLICATE_CONFLICT")


def test_unknown_and_empty_cells_warn_never_error():
    grid = _jan_grid()
    grid[7][2] = "CL"   # first day cell of employee 1
    grid[7][3] = ""     # blank
    res = parse_leave_workbook(_grid_bytes(grid, "xlsx"), CODE_MAP, DEPT)
    assert not res.sheets[0].blocked
    assert _codes(res.issues, "CELL_UNKNOWN_CODE")
    assert _codes(res.issues, "CELL_EMPTY")
    kinds = {(r.date, r.kind) for r in res.sheets[0].rows
             if r.employee_id == "90001" and r.date.day in (1, 2)}
    assert (date(2026, 1, 1), "unknown") in kinds
    assert (date(2026, 1, 2), "unknown") in kinds


def test_interior_dash_and_weekend_mismatch():
    grid = _jan_grid()
    # employee 3 (row 9): force W onto a Monday, EL onto a Saturday.
    # Jan 2026: Thu 1, Fri 2, Sat 3, Mon 5.
    grid[9][2 + 4] = "W"   # Mon 5 Jan
    grid[9][2 + 2] = "EL"  # Sat 3 Jan
    # employee 4 (row 10): interior dash on Wed 7 Jan.
    grid[10][2 + 6] = "-"
    res = parse_leave_workbook(_grid_bytes(grid, "xlsx"), CODE_MAP, DEPT)
    assert len(_codes(res.issues, "CELL_WEEKEND_MISMATCH")) == 2
    assert _codes(res.issues, "CELL_INTERIOR_DASH")


def test_provisional_last_column_excluded():
    grid = fix.build_grid(2026, 2, 4, {"provisional"}, 1)
    res = parse_leave_workbook(_grid_bytes(grid, "xlsx"), CODE_MAP, DEPT)
    sheet = res.sheets[0]
    assert not sheet.blocked
    assert _codes(res.issues, "LAST_COLUMN_PROVISIONAL")
    assert sheet.provisional_excluded == 4
    assert len(sheet.rows) == 4 * 27
    assert res.coverage_through == date(2026, 2, 27)


def test_no_provisional_when_stable():
    res = parse_leave_workbook(_grid_bytes(_jan_grid(), "xlsx"), CODE_MAP, DEPT)
    assert not _codes(res.issues, "LAST_COLUMN_PROVISIONAL")
    assert res.coverage_through == date(2026, 1, 31)


def test_names_in_preview_only_not_staging():
    res = parse_leave_workbook(_grid_bytes(_jan_grid(), "xlsx"), CODE_MAP, DEPT)
    assert res.sheets[0].names["90001"] == "Test User 1"
    for row in res.sheets[0].rows:
        assert not hasattr(row, "name")


def test_code_counts_tally():
    res = parse_leave_workbook(_grid_bytes(_jan_grid(), "xlsx"), CODE_MAP, DEPT)
    assert sum(res.code_counts.values()) == 4 * 31
    assert res.code_counts["P"] > 0 and res.code_counts["W"] > 0
