"""Zoho leave-report parser: file bytes in, calendar rows + issues out.

Pure function — no database access. The caller loads ``leave_code_map``
and passes it in, so mapping changes + reprocess fix history without
re-uploading (spec D2). Never carries employee names into staging rows;
names are returned separately for the in-flight preview only.

Layout contract (spec §2): one workbook, one sheet per month; header is
the first row within the first 15 where one of the first 3 cells equals
``Employee Id``; ``Start Date``/``End Date`` labelled cells give the
period; day columns are labelled ``{d} - {Mon}``.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from io import BytesIO

MAX_FILE_BYTES = 10 * 1024 * 1024
_OLE2_MAGIC = bytes.fromhex("D0CF11E0")
_ZIP_MAGIC = b"PK"

_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DAY_LABEL_RE = re.compile(r"^(\d{1,2})\s*-\s*([A-Za-z]+)$")
_COMPONENT_RE = re.compile(r"^(0\.5|\.5)?([A-Z0-9][A-Z0-9\-]*|-)$")


class FileTooLargeError(Exception):
    pass


class FileTypeUnsupportedError(Exception):
    pass


class FileUnreadableError(Exception):
    pass


@dataclass
class StagingRow:
    employee_id: str
    date: date
    raw_code: str
    kind: str
    leave_code: str | None
    fraction: float
    zoho_presence: bool | None
    provisional: bool = False


@dataclass
class Issue:
    severity: str  # error | warning | info
    code: str
    sheet: str | None = None
    row: int | None = None
    col: int | None = None
    employee_id: str | None = None
    date: date | None = None
    occurrences: int = 1
    message: str = ""
    samples: list = field(default_factory=list)


@dataclass
class SheetResult:
    name: str
    blocked: bool = False
    start_date: date | None = None
    end_date: date | None = None
    department_label: str | None = None
    rows: list[StagingRow] = field(default_factory=list)
    # employee_id -> name from the file; preview payload only, never stored.
    names: dict[str, str] = field(default_factory=dict)
    day_columns: int = 0
    provisional_excluded: int = 0


@dataclass
class ParsedImport:
    file_sha256: str
    sheets: list[SheetResult] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    code_counts: Counter = field(default_factory=Counter)
    period_start: date | None = None
    period_end: date | None = None
    coverage_through: date | None = None

    @property
    def rows(self) -> list[StagingRow]:
        return [r for s in self.sheets if not s.blocked for r in s.rows]


# --- cell normalisation ------------------------------------------------------


def normalize_employee_id(value: object) -> str | None:
    """Return the match key (trimmed, inner spaces stripped) or None.

    None means missing (blank) or invalid (non-integer float, error cell).
    Leading zeros are stripped on the *match key* only (spec D3); callers
    comparing against the directory must apply the same rule.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    text = str(value).strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        return None
    if text.startswith("_ERROR:"):
        return None
    return text


def match_key(employee_id: str) -> str:
    return employee_id.strip().lstrip("0") or "0"


def normalize_cell(value: object) -> str:
    """Stringify, trim, uppercase, collapse whitespace. Blank -> ''."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return "?"
    text = re.sub(r"\s+", "", str(value).strip().upper())
    return text


# --- code grammar (spec §2) --------------------------------------------------


def derive_day(raw: str, code_map: dict) -> tuple[str, str | None, float, bool | None, str | None]:
    """Map a normalised cell to (kind, leave_code, fraction, zoho_presence, issue_code).

    ``code_map`` maps base code -> {"kind": ..., "leave_group": ...}.
    Unknown/unparseable cells yield kind ``unknown`` with an issue code;
    the raw value is always preserved by the caller (spec D2/D8).
    """
    if raw == "":
        return "unknown", None, 1.0, None, "CELL_EMPTY"
    if raw == "?":
        return "unknown", None, 1.0, None, "CELL_CODE_UNPARSEABLE"
    parts = raw.split("/")
    if len(parts) > 2:
        return "unknown", None, 1.0, None, "CELL_CODE_UNPARSEABLE"
    parsed: list[tuple[str, float]] = []
    for part in parts:
        m = _COMPONENT_RE.match(part)
        if not m:
            return "unknown", None, 1.0, None, "CELL_CODE_UNPARSEABLE"
        frac = 0.5 if m.group(1) else 1.0
        parsed.append((m.group(2), frac))
    base, base_frac = parsed[0]
    entry = code_map.get(base)
    if entry is None:
        return "unknown", None, 1.0, None, "CELL_UNKNOWN_CODE"
    kind = entry["kind"]
    leave_code = base if kind == "leave" else None
    if len(parsed) == 1:
        presence: bool | None = True if base == "P" else (False if base == "A" else None)
        return kind, leave_code, base_frac, presence, None
    # Compound X/Y: day kind from X; Y must be a presence half (P/A).
    other, other_frac = parsed[1]
    if other not in ("P", "A"):
        return "unknown", None, 1.0, None, "CELL_CODE_UNPARSEABLE"
    fraction = 0.5 if (base_frac == 0.5 or other_frac == 0.5) else 1.0
    return kind, leave_code, fraction, (other == "P"), None


# --- workbook loading (magic bytes, not extension) --------------------------


class _TableParser(HTMLParser):
    """Minimal <table> extractor for HTML-disguised .xls exports."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._cur: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self._cur = []
            self.tables.append(self._cur)
        elif tag == "tr" and self._cur is not None:
            self._row = []
            self._cur.append(self._row)
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell))
            self._cell = None
        elif tag == "tr":
            self._row = None
        elif tag == "table":
            self._cur = None


def _load_grids(data: bytes) -> list[tuple[str, list[list[object]]]]:
    """Return [(sheet_name, rows)] with dates as datetime/date objects."""
    if data[:4] == _OLE2_MAGIC:
        try:
            import xlrd
        except ImportError as exc:
            raise FileUnreadableError(f"xls support unavailable: {exc}")
        try:
            book = xlrd.open_workbook(file_contents=data)
        except Exception as exc:
            raise FileUnreadableError(f"unreadable xls: {exc}")
        out = []
        for sheet in book.sheets():
            rows: list[list[object]] = []
            for r in range(sheet.nrows):
                row: list[object] = []
                for c in range(sheet.ncols):
                    t = sheet.cell_type(r, c)
                    v = sheet.cell_value(r, c)
                    if t == xlrd.XL_CELL_DATE:
                        try:
                            row.append(xlrd.xldate_as_datetime(v, book.datemode))
                        except Exception:
                            row.append("?")
                    elif t in (xlrd.XL_CELL_BLANK, xlrd.XL_CELL_EMPTY):
                        row.append(None)
                    elif t == xlrd.XL_CELL_ERROR:
                        row.append("?")
                    else:
                        row.append(v)
                rows.append(row)
            out.append((sheet.name, rows))
        return out
    if data[:2] == _ZIP_MAGIC:
        try:
            import openpyxl
        except ImportError as exc:
            raise FileUnreadableError(f"xlsx support unavailable: {exc}")
        try:
            book = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise FileUnreadableError(f"unreadable xlsx: {exc}")
        out = []
        for ws in book.worksheets:
            rows = [[cell.value for cell in row] for row in ws.iter_rows()]
            out.append((ws.title, rows))
        return out
    # HTML-disguised export?
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise FileTypeUnsupportedError("not an xls, xlsx, or HTML-table file")
    if "<table" not in text.lower():
        raise FileTypeUnsupportedError("not an xls, xlsx, or HTML-table file")
    parser = _TableParser()
    try:
        parser.feed(text)
    except Exception as exc:
        raise FileUnreadableError(f"unreadable HTML export: {exc}")
    if not parser.tables:
        raise FileTypeUnsupportedError("no tables found in HTML export")
    return [(f"Sheet{i + 1}", table) for i, table in enumerate(parser.tables)]


def _coerce_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _cell_text(value: object) -> str:
    if value is None or isinstance(value, (datetime, date, bool)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# --- sheet pipeline ----------------------------------------------------------


def _find_header(rows: list[list[object]]) -> int | None:
    for r in range(min(15, len(rows))):
        first = [_cell_text(rows[r][c]).strip().lower() if c < len(rows[r]) else ""
                 for c in range(3)]
        if any(v == "employee id" for v in first):
            return r
    return None


def _find_dates(rows: list[list[object]]) -> tuple[date | None, date | None]:
    start = end = None
    for r in range(min(12, len(rows))):
        for c in range(min(6, len(rows[r]))):
            label = _cell_text(rows[r][c]).strip().lower()
            if label == "start date" and c + 1 < len(rows[r]):
                start = _coerce_date(rows[r][c + 1])
            elif label == "end date" and c + 1 < len(rows[r]):
                end = _coerce_date(rows[r][c + 1])
    return start, end


def _expected_day_labels(start: date, end: date) -> list[str]:
    from datetime import timedelta

    labels = []
    cur = start
    while cur <= end:
        labels.append(f"{cur.day} - {cur.strftime('%b')}")
        cur += timedelta(days=1)
    return labels


def _parse_sheet(name: str, rows: list[list[object]], code_map: dict,
                 seen_months: set[tuple[int, int]],
                 expected_departments: set[str]) -> tuple[SheetResult, list[Issue]]:
    issues: list[Issue] = []
    sheet = SheetResult(name=name)
    if not rows:
        issues.append(Issue("warning", "SHEET_SKIPPED_NO_HEADER", sheet=name,
                            message="Sheet is empty"))
        sheet.blocked = True
        return sheet, issues

    sheet.department_label = _cell_text(rows[0][1]).strip() if len(rows[0]) > 1 else ""
    if sheet.department_label and sheet.department_label not in expected_departments:
        issues.append(Issue("warning", "DEPARTMENT_MISMATCH", sheet=name,
                            message=f"B1 {sheet.department_label!r} not in expected labels"))

    hdr = _find_header(rows)
    if hdr is None:
        issues.append(Issue("warning", "SHEET_SKIPPED_NO_HEADER", sheet=name,
                            message="No 'Employee Id' header row in first 15 rows"))
        sheet.blocked = True
        return sheet, issues

    start, end = _find_dates(rows)
    if start is None or end is None or end < start:
        issues.append(Issue("error", "SHEET_DATES_INVALID", sheet=name,
                            message="Bad or missing Start/End Date, or End before Start"))
        sheet.blocked = True
        return sheet, issues
    sheet.start_date, sheet.end_date = start, end

    month_key = (start.year, start.month)
    if month_key in seen_months:
        issues.append(Issue("error", "SHEET_PERIOD_OVERLAP", sheet=name,
                            message="A sheet already covers this month; later sheet blocked"))
        sheet.blocked = True
        return sheet, issues
    seen_months.add(month_key)

    header_cells = rows[hdr]
    labels = [_cell_text(header_cells[c]).strip() if c < len(header_cells) else ""
              for c in range(2, len(header_cells))]
    expected = _expected_day_labels(start, end)
    norm = [re.sub(r"\s+", " ", lb).replace("  ", " ") for lb in labels]
    if len(labels) != len(expected) or any(
            a.lower() != b.lower() for a, b in zip(norm, expected)):
        issues.append(Issue("error", "SHEET_HEADER_MISMATCH", sheet=name,
                            message=f"Expected {len(expected)} day columns from "
                                    f"{start} to {end}, found {len(labels)}"))
        sheet.blocked = True
        return sheet, issues
    sheet.day_columns = len(expected)

    day_dates = []
    from datetime import timedelta
    cur = start
    while cur <= end:
        day_dates.append(cur)
        cur += timedelta(days=1)

    # D5 provisional last column: '-' share exceeds previous column by >10pp.
    provisional_col: int | None = None
    if len(day_dates) >= 2:
        def dash_share(col: int) -> float:
            tot = dash = 0
            for r in range(hdr + 1, len(rows)):
                if _emp_id_cell(rows[r]) is None:
                    continue
                tot += 1
                if normalize_cell(rows[r][col] if col < len(rows[r]) else None) == "-":
                    dash += 1
            return dash / tot if tot else 0.0

        last, prev = len(header_cells) - 1, len(header_cells) - 2
        if dash_share(last) - dash_share(prev) > 0.10:
            provisional_col = last
            issues.append(Issue("info", "LAST_COLUMN_PROVISIONAL", sheet=name,
                                date=day_dates[-1],
                                message=f"Last column {day_dates[-1]} is provisional "
                                        "and excluded from import"))

    seen_ids: dict[str, str] = {}  # match key -> first raw row signature
    row_errors = 0
    row_total = 0
    for r in range(hdr + 1, len(rows)):
        raw_row = rows[r]
        emp_raw = _emp_id_cell(raw_row)
        if emp_raw is None and all(normalize_cell(v) == "" for v in raw_row[1:]):
            continue  # fully blank row: skip, never stop (rows may follow)
        emp_id = normalize_employee_id(emp_raw)
        if emp_id is None:
            code = "ROW_ID_MISSING" if emp_raw is None or _cell_text(emp_raw).strip() == "" else "ROW_ID_INVALID"
            issues.append(Issue("error", code, sheet=name, row=r,
                                message="Row skipped: missing or invalid employee ID"))
            row_errors += 1
            row_total += 1
            continue
        row_total += 1
        key = match_key(emp_id)
        signature_cells = [normalize_cell(v) for v in raw_row[2:]]
        signature = "|".join(signature_cells)
        if key in seen_ids:
            if seen_ids[key] == signature:
                issues.append(Issue("warning", "ROW_DUPLICATE_IDENTICAL", sheet=name,
                                    row=r, employee_id=emp_id,
                                    message="Identical duplicate row deduplicated"))
                continue
            issues.append(Issue("error", "ROW_DUPLICATE_CONFLICT", sheet=name,
                                row=r, employee_id=emp_id,
                                message="Conflicting duplicate row: sheet blocked"))
            sheet.blocked = True
            return sheet, issues
        seen_ids[key] = signature

        name = _cell_text(raw_row[1]).strip() if len(raw_row) > 1 else ""
        sheet.names[emp_id] = name

        seq = [normalize_cell(raw_row[c] if c < len(raw_row) else None)
               for c in range(2, len(header_cells))]
        cell_issues: list[tuple[int, str, str]] = []  # (col, issue_code, raw)
        kinds: list[tuple[str, str | None, float, bool | None]] = []
        for i, raw in enumerate(seq):
            kind, leave_code, frac, presence, issue_code = derive_day(raw, code_map)
            kinds.append((kind, leave_code, frac, presence))
            if issue_code:
                cell_issues.append((i, issue_code, raw))
        # interior dash: '-' with non-dash days on both sides.
        for i, raw in enumerate(seq):
            if raw == "-" and any(x != "-" for x in seq[:i]) and any(x != "-" for x in seq[i + 1:]):
                cell_issues.append((i, "CELL_INTERIOR_DASH", raw))
        # weekend sanity: W on Mon–Fri, or EL/SL/L on Sat/Sun.
        for i, raw in enumerate(seq):
            first = raw.split("/")[0]
            base = re.sub(r"^(0\.5|\.5)", "", first)
            wd = day_dates[i].weekday()
            if raw == "W" and wd < 5:
                cell_issues.append((i, "CELL_WEEKEND_MISMATCH", raw))
            elif base in ("EL", "SL", "L") and wd >= 5:
                cell_issues.append((i, "CELL_WEEKEND_MISMATCH", raw))

        for i, issue_code, raw in cell_issues:
            # Message carries the raw value but not the date (the date lives
            # in Issue.date): routers aggregate repetitive issues per raw code.
            issues.append(Issue("warning", issue_code, sheet=name, row=r,
                                col=2 + i, employee_id=emp_id, date=day_dates[i],
                                message=f"{issue_code}: {raw!r}"))

        for i, (kind, leave_code, frac, presence) in enumerate(kinds):
            provisional = (2 + i) == provisional_col
            if provisional:
                sheet.provisional_excluded += 1
                continue
            sheet.rows.append(StagingRow(
                employee_id=emp_id, date=day_dates[i], raw_code=seq[i],
                kind=kind, leave_code=leave_code, fraction=frac,
                zoho_presence=presence, provisional=False))

    if row_total and row_errors / row_total > 0.05:
        issues.append(Issue("error", "TOO_MANY_ROW_ERRORS", sheet=name,
                            message=f"{row_errors}/{row_total} rows failed (>5%): sheet blocked"))
        sheet.blocked = True
    return sheet, issues


def _emp_id_cell(raw_row: list[object]) -> object:
    if not raw_row:
        return None
    v = raw_row[0]
    if v is None:
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


# --- entry point -------------------------------------------------------------


def parse_leave_workbook(data: bytes, code_map: dict,
                         expected_departments: set[str] | None = None) -> ParsedImport:
    """Parse raw file bytes into staging rows + issues.

    Raises FileTooLargeError / FileTypeUnsupportedError / FileUnreadableError.
    """
    if len(data) > MAX_FILE_BYTES:
        raise FileTooLargeError(f"file too large: {len(data)} bytes")
    digest = hashlib.sha256(data).hexdigest()
    grids = _load_grids(data)  # may raise type/unreadable errors
    if not grids:
        raise FileUnreadableError("no sheets found")
    expected_departments = expected_departments or set()
    result = ParsedImport(file_sha256=digest)
    seen_months: set[tuple[int, int]] = set()
    for name, rows in grids:
        sheet, issues = _parse_sheet(name, rows, code_map, seen_months,
                                     expected_departments)
        result.sheets.append(sheet)
        result.issues.extend(issues)
    valid = [s for s in result.sheets if not s.blocked]
    if not valid:
        result.issues.append(Issue("error", "NO_VALID_SHEETS",
                                   message="Nothing to import: every sheet blocked"))
    else:
        starts = [s.start_date for s in valid if s.start_date]
        ends = [s.end_date for s in valid if s.end_date]
        if starts and ends:
            result.period_start = min(starts)
            result.period_end = max(ends)
        through = [r.date for r in result.rows]
        if through:
            result.coverage_through = max(through)
    for row in result.rows:
        result.code_counts[row.raw_code or "<BLANK>"] += 1
    return result
