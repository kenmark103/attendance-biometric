from dataclasses import dataclass
from datetime import date, datetime, tzinfo

REQUIRED_COLUMNS = (
    "UserID", "UserName", "ProcessDate", "Punch1", "Punch2",
    "WorkingShift", "LateIn", "EarlyOut", "Overtime", "WorkTime",
)


class PayloadError(Exception):
    pass


@dataclass(frozen=True)
class DailyRow:
    user_id: str
    user_name: str
    process_date: date
    punch1: datetime | None
    punch2: datetime | None
    working_shift: str | None
    late_in_min: int | None
    early_out_min: int | None
    overtime_min: int | None
    work_time_min: int | None


@dataclass
class ParseResult:
    rows: list[DailyRow]
    data_lines: int
    malformed: int
    duplicates: int


def _dt(value: str, tz: tzinfo) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    return datetime.strptime(value, "%d/%m/%Y %H:%M:%S").replace(tzinfo=tz)


def _int(value: str) -> int | None:
    value = value.strip()
    return int(value) if value else None


def parse_payload(text: str, tz: tzinfo) -> ParseResult:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise PayloadError("empty response")

    header = lines[0]
    if not header.lower().startswith("userid|"):
        raise PayloadError("unexpected response: " + header[:200])

    cols = [c.strip().lower() for c in header.split("|")]
    missing = [n for n in REQUIRED_COLUMNS if n.lower() not in cols]
    if missing:
        raise PayloadError("missing columns: " + ", ".join(missing))
    ix = {n: cols.index(n.lower()) for n in REQUIRED_COLUMNS}

    rows: dict[tuple[str, date], DailyRow] = {}
    malformed = 0
    duplicates = 0

    for ln in lines[1:]:
        f = ln.split("|")
        if len(f) != len(cols):
            malformed += 1
            continue
        try:
            user_id = f[ix["UserID"]].strip()
            if not user_id:
                raise ValueError("empty user id")
            row = DailyRow(
                user_id=user_id,
                user_name=f[ix["UserName"]].strip() or user_id,
                process_date=datetime.strptime(
                    f[ix["ProcessDate"]].strip(), "%d/%m/%Y"
                ).date(),
                punch1=_dt(f[ix["Punch1"]], tz),
                punch2=_dt(f[ix["Punch2"]], tz),
                working_shift=f[ix["WorkingShift"]].strip() or None,
                late_in_min=_int(f[ix["LateIn"]]),
                early_out_min=_int(f[ix["EarlyOut"]]),
                overtime_min=_int(f[ix["Overtime"]]),
                work_time_min=_int(f[ix["WorkTime"]]),
            )
        except ValueError:
            malformed += 1
            continue
        key = (row.user_id, row.process_date)
        if key in rows:
            duplicates += 1
        rows[key] = row  # last occurrence wins

    return ParseResult(
        rows=list(rows.values()),
        data_lines=len(lines) - 1,
        malformed=malformed,
        duplicates=duplicates,
    )
