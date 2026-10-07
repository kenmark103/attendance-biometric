import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Nairobi")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    cosec_base_url: str
    cosec_user: str
    cosec_password: str
    database_url: str
    cosec_timeout_s: int
    cosec_max_range_days: int
    poll_interval_s: int
    poll_lookback_days: int
    max_plausible_span_min: int
    max_malformed_ratio: float


def _normalize_db_url(url: str) -> str:
    """Map the repo's single DATABASE_URL pattern to a SQLAlchemy URL.

    The repo standard is ``postgresql://user:pass@host:port/db`` (psycopg2).
    SQLAlchemy needs an explicit driver (``postgresql+psycopg2://``). The
    mapping lives here and nowhere else, per the ingestion spec.
    """
    url = url.strip()
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def load_settings(require_db: bool = True) -> Settings:
    env = os.environ
    required = ["COSEC_BASE_URL", "COSEC_USER", "COSEC_PASSWORD"]
    if require_db:
        required.append("DATABASE_URL")
    missing = [n for n in required if not env.get(n, "").strip()]
    if missing:
        raise ConfigError("Missing environment variables: " + ", ".join(missing))
    return Settings(
        cosec_base_url=env["COSEC_BASE_URL"].strip().rstrip("/"),
        cosec_user=env["COSEC_USER"],
        cosec_password=env["COSEC_PASSWORD"],
        database_url=_normalize_db_url(env.get("DATABASE_URL", "")),
        cosec_timeout_s=int(env.get("COSEC_TIMEOUT_SECONDS", "60")),
        cosec_max_range_days=int(env.get("COSEC_MAX_RANGE_DAYS", "31")),
        poll_interval_s=int(env.get("POLL_INTERVAL_SECONDS", "300")),
        poll_lookback_days=int(env.get("POLL_LOOKBACK_DAYS", "3")),
        max_plausible_span_min=int(env.get("MAX_PLAUSIBLE_SPAN_MIN", "960")),
        max_malformed_ratio=float(env.get("MAX_MALFORMED_RATIO", "0.05")),
    )
