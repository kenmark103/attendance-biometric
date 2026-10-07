import logging
import time
from datetime import date

import requests

from .config import Settings

log = logging.getLogger(__name__)

RETRY_STATUS = {500, 502, 503, 504}
RETRY_DELAYS = (2, 4, 8)  # seconds; 1 initial attempt + 3 retries


class CosecError(Exception):
    pass


class CosecAuthError(CosecError):
    pass


class CosecHttpError(CosecError):
    pass


def build_url(base_url: str, d_from: date, d_to: date) -> str:
    return (
        f"{base_url}/attendance-daily"
        f"?action=get;date-range={d_from:%d%m%Y}-{d_to:%d%m%Y}"
    )


def fetch_range(settings: Settings, d_from: date, d_to: date) -> str:
    if d_from > d_to:
        raise ValueError("d_from must be <= d_to")
    if (d_to - d_from).days + 1 > settings.cosec_max_range_days:
        raise ValueError("range exceeds COSEC_MAX_RANGE_DAYS")

    url = build_url(settings.cosec_base_url, d_from, d_to)
    last_exc: Exception | None = None

    with requests.Session() as session:
        session.auth = (settings.cosec_user, settings.cosec_password)
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                resp = session.get(url, timeout=(5, settings.cosec_timeout_s))
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
            else:
                if resp.status_code in (401, 403):
                    raise CosecAuthError(
                        f"COSEC rejected credentials (HTTP {resp.status_code})"
                    )
                if resp.status_code in RETRY_STATUS:
                    last_exc = CosecHttpError(f"HTTP {resp.status_code}")
                elif resp.status_code != 200:
                    raise CosecHttpError(f"HTTP {resp.status_code}")
                else:
                    return resp.content.decode("utf-8-sig", errors="replace")
            if attempt < len(RETRY_DELAYS):
                log.warning("COSEC fetch attempt %d failed; retrying", attempt + 1)
                time.sleep(RETRY_DELAYS[attempt])

    raise CosecError(
        f"COSEC unreachable after retries: {type(last_exc).__name__}: {last_exc}"
    )
