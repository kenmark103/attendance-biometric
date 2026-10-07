import argparse
import logging
import sys
from collections import Counter
from datetime import date, datetime

from sqlalchemy import create_engine

from .config import TZ, ConfigError, load_settings
from .cosec_client import fetch_range
from .parser import parse_payload
from .quality import classify
from .scope import import_scope
from .service import backfill_months, poll_once, poll_window, run_loop

log = logging.getLogger(__name__)


def _engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


def cmd_check(_args) -> int:
    try:
        settings = load_settings(require_db=False)
        d_from, d_to = poll_window(settings)
        chunk_text = fetch_range(settings, d_from, d_to)
        result = parse_payload(chunk_text, TZ)
        users = {r.user_id for r in result.rows}
        counts = Counter(classify(r, settings.max_plausible_span_min) for r in result.rows)
        print(f"OK rows={len(result.rows)} users={len(users)} malformed={result.malformed} quality={dict(counts)}")
        return 0
    except Exception as exc:
        print(f"check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


def cmd_poll_once(_args) -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    engine = _engine(settings.database_url)
    summary = poll_once(engine, settings)
    print(
        f"status={summary.status} received={summary.received}"
        f" written={summary.written} malformed={summary.malformed} run_id={summary.run_id}"
    )
    return {"success": 0, "skipped": 0}.get(summary.status, 1)


def cmd_run(_args) -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    engine = _engine(settings.database_url)
    run_loop(engine, settings)
    return 0


def cmd_backfill(args) -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    today = datetime.now(TZ).astimezone(TZ).date()
    if args.year is not None:
        if args.year > today.year:
            print(f"year {args.year} is in the future", file=sys.stderr)
            return 2
        d_from = date(args.year, 1, 1)
        d_to = min(date(args.year, 12, 31), today)
    else:
        try:
            d_from = date.fromisoformat(args.from_date)
        except ValueError:
            print(f"bad --from date: {args.from_date}", file=sys.stderr)
            return 2
        if args.to is None:
            d_to = today
        else:
            try:
                d_to = date.fromisoformat(args.to)
            except ValueError:
                print(f"bad --to date: {args.to}", file=sys.stderr)
                return 2
            if d_to > today:
                log.warning("clipping --to %s to today %s", d_to, today)
                d_to = today
        if d_from > d_to:
            print(f"--from {d_from} is after --to {d_to}", file=sys.stderr)
            return 2
    engine = _engine(settings.database_url)
    months = len(list(__import__("app.ingestion.service", fromlist=["month_ranges"]).month_ranges(d_from, d_to)))
    failed_start = backfill_months(engine, settings, d_from, d_to, args.pause)
    if failed_start is None:
        print(f"backfill status=success months={months}")
        return 0
    print(f"backfill status=failed restart_from={failed_start.isoformat()}")
    return 1


def cmd_import_scope(args) -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    engine = _engine(settings.database_url)
    try:
        import_scope(engine, args.csv, args.apply)
    except SystemExit as exc:
        return int(exc.code or 2)
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m app.ingestion.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check")
    p_backfill = sub.add_parser("backfill")
    group = p_backfill.add_mutually_exclusive_group(required=True)
    group.add_argument("--year", type=int)
    group.add_argument("--from", dest="from_date")
    p_backfill.add_argument("--to", default=None)
    p_backfill.add_argument("--pause", type=int, default=2)
    sub.add_parser("poll-once")
    sub.add_parser("run")
    p_scope = sub.add_parser("import-scope")
    p_scope.add_argument("--csv", required=True)
    p_scope.add_argument("--apply", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "check":
        return cmd_check(args)
    if args.command == "backfill":
        return cmd_backfill(args)
    if args.command == "poll-once":
        return cmd_poll_once(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "import-scope":
        return cmd_import_scope(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
