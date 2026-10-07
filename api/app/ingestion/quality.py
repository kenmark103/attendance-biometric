from datetime import datetime

from .parser import DailyRow


def _minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def span_minutes(p1: datetime, p2: datetime) -> int:
    return int((_minute(p2) - _minute(p1)).total_seconds() // 60)


def classify(row: DailyRow, max_span_min: int) -> str:
    if row.punch1 is None and row.punch2 is None:
        return "no_punch"
    if row.punch1 is None:
        return "anomaly"          # out-punch without an in-punch
    if row.punch2 is None:
        return "open"             # in-punch only (in progress or missed out)
    span = span_minutes(row.punch1, row.punch2)
    if span < 0:
        return "anomaly"
    if row.work_time_min is not None and abs(row.work_time_min - span) > 1:
        return "mismatch"         # COSEC's WorkTime contradicts its own punches
    if span > max_span_min:
        return "long_span"        # consistent but implausible (pairing across days)
    return "ok"


def is_processed(row: DailyRow) -> bool:
    return row.work_time_min is not None
