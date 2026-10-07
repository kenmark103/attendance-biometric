from app.ingestion.config import TZ
from app.ingestion.parser import parse_payload
from app.ingestion.quality import classify, is_processed

H = "UserID|UserName|ProcessDate|Punch1|Punch2|WorkingShift|LateIn|EarlyOut|Overtime|WorkTime"


def L(*fields: str) -> str:
    assert len(fields) == 10
    return "|".join(fields)


A = L("20001", "Test Day", "02/10/2026", "02/10/2026 09:20:16", "02/10/2026 16:39:27", "AL", "0", "0", "0", "439")
B = L("20002", "Test Night", "01/10/2026", "01/10/2026 18:41:53", "02/10/2026 01:18:21", "AL", "0", "0", "0", "397")
C = L("20003", "Test Open", "06/10/2026", "06/10/2026 12:54:28", "", "AL", "534", "0", "0", "0")
D = L("20004", "Test Unprocessed", "06/10/2026", "", "", "AL", "", "", "", "")
E = L("0001", "Test Blank", "06/10/2026", "", "", "", "", "", "", "")
F = L("20005", "Test Zero", "03/10/2026", "", "", "", "0", "0", "0", "0")


def row(line: str):
    res = parse_payload(H + "\n" + line, TZ)
    assert len(res.rows) == 1
    return res.rows[0]


def test_ok_rows():
    assert classify(row(A), 960) == "ok"
    assert classify(row(B), 960) == "ok"  # overnight


def test_open_row():
    assert classify(row(C), 960) == "open"


def test_no_punch_rows():
    assert classify(row(D), 960) == "no_punch"
    assert classify(row(E), 960) == "no_punch"
    assert classify(row(F), 960) == "no_punch"


def test_mismatch_row():
    line = L("20006", "Test Mismatch", "01/10/2026", "01/10/2026 10:58:24", "01/10/2026 14:19:10", "", "0", "0", "0", "2013")
    assert classify(row(line), 960) == "mismatch"


def test_long_span_row():
    line = L("20007", "Test Long", "02/10/2026", "02/10/2026 06:52:19", "03/10/2026 10:15:43", "", "0", "0", "0", "1643")
    assert classify(row(line), 960) == "long_span"


def test_overtime_row_ok():
    line = L("20008", "Test Overtime", "05/10/2026", "05/10/2026 14:44:04", "06/10/2026 01:37:35", "AL", "0", "0", "113", "653")
    assert classify(row(line), 960) == "ok"


def test_tolerance_boundary():
    base = ["20001", "Test Day", "02/10/2026", "02/10/2026 09:20:16", "02/10/2026 16:39:27", "AL", "0", "0", "0"]
    assert classify(row(L(*base, "440")), 960) == "ok"  # tolerance of 1
    assert classify(row(L(*base, "442")), 960) == "mismatch"


def test_anomaly_rows():
    punch2_only = L("20011", "No In", "02/10/2026", "", "02/10/2026 16:39:27", "AL", "0", "0", "0", "439")
    assert classify(row(punch2_only), 960) == "anomaly"
    reversed_punches = L("20012", "Reversed", "02/10/2026", "02/10/2026 16:39:27", "02/10/2026 09:20:16", "AL", "0", "0", "0", "0")
    assert classify(row(reversed_punches), 960) == "anomaly"


def test_is_processed():
    assert is_processed(row(A)) is True
    assert is_processed(row(F)) is True  # zeros are processed, not missing
    assert is_processed(row(D)) is False
    assert is_processed(row(E)) is False
