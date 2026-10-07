from datetime import date

import pytest

from app.ingestion.config import TZ
from app.ingestion.parser import PayloadError, parse_payload

H = "UserID|UserName|ProcessDate|Punch1|Punch2|WorkingShift|LateIn|EarlyOut|Overtime|WorkTime"


def L(*fields: str) -> str:
    assert len(fields) == 10, f"test helper must build 10 fields, got {len(fields)}"
    return "|".join(fields)


A = L("20001", "Test Day", "02/10/2026", "02/10/2026 09:20:16", "02/10/2026 16:39:27", "AL", "0", "0", "0", "439")
B = L("20002", "Test Night", "01/10/2026", "01/10/2026 18:41:53", "02/10/2026 01:18:21", "AL", "0", "0", "0", "397")
C = L("20003", "Test Open", "06/10/2026", "06/10/2026 12:54:28", "", "AL", "534", "0", "0", "0")
D = L("20004", "Test Unprocessed", "06/10/2026", "", "", "AL", "", "", "", "")
E = L("0001", "Test Blank", "06/10/2026", "", "", "", "", "", "", "")
F = L("20005", "Test Zero", "03/10/2026", "", "", "", "0", "0", "0", "0")
G = L("20009", "Bad Date", "99/99/2026", "", "", "", "", "", "", "")


def test_row_a_day_shift():
    res = parse_payload(H + "\n" + A, TZ)
    assert res.data_lines == 1 and res.malformed == 0
    row = res.rows[0]
    assert row.punch1 is not None and row.punch1.isoformat() == "2026-10-02T09:20:16+03:00"
    assert row.working_shift == "AL"
    assert row.work_time_min == 439


def test_row_b_overnight():
    res = parse_payload(H + "\n" + B, TZ)
    row = res.rows[0]
    assert row.process_date == date(2026, 10, 1)
    assert row.punch2 is not None and row.punch2.date() == date(2026, 10, 2)


def test_row_c_open_punch():
    res = parse_payload(H + "\n" + C, TZ)
    row = res.rows[0]
    assert row.punch2 is None
    assert row.late_in_min == 534


def test_row_d_unprocessed():
    res = parse_payload(H + "\n" + D, TZ)
    row = res.rows[0]
    assert row.working_shift == "AL"
    assert row.punch1 is None and row.punch2 is None
    assert (row.late_in_min, row.early_out_min, row.overtime_min, row.work_time_min) == (None, None, None, None)


def test_row_e_leading_zeros_kept():
    res = parse_payload(H + "\n" + E, TZ)
    row = res.rows[0]
    assert row.user_id == "0001"
    assert isinstance(row.user_id, str)
    assert row.working_shift is None


def test_row_f_zero_vs_null():
    res = parse_payload(H + "\n" + F, TZ)
    row = res.rows[0]
    assert (row.late_in_min, row.early_out_min, row.overtime_min, row.work_time_min) == (0, 0, 0, 0)
    assert row.working_shift is None


def test_row_g_bad_date_malformed():
    res = parse_payload(H + "\n" + G, TZ)
    assert res.malformed == 1 and res.rows == []


def test_row_h_short_line_malformed():
    res = parse_payload(H + "\n" + "20010|Short|02/10/2026|", TZ)
    assert res.malformed == 1 and res.rows == []


def test_row_i_duplicates_last_wins():
    line2 = L("20001", "Test Day Renamed", "02/10/2026", "02/10/2026 09:20:16", "02/10/2026 16:39:27", "AL", "0", "0", "0", "439")
    res = parse_payload(H + "\n" + A + "\n" + line2, TZ)
    assert len(res.rows) == 1 and res.duplicates == 1
    assert res.rows[0].user_name == "Test Day Renamed"


def test_error_payload_rejected():
    with pytest.raises(PayloadError):
        parse_payload("Error: invalid credentials", TZ)


def test_missing_column_rejected():
    bad_h = "UserID|UserName|ProcessDate|Punch1|Punch2|WorkingShift|LateIn|EarlyOut|Overtime"
    with pytest.raises(PayloadError):
        parse_payload(bad_h + "\n" + A, TZ)


def test_empty_payload_rejected():
    with pytest.raises(PayloadError):
        parse_payload("", TZ)


def test_extra_columns_still_parse():
    res = parse_payload(H + "|ExtraCol\n" + A + "|zzz", TZ)
    assert len(res.rows) == 1
