"""Transactional metadata-only audit logging for admin writes."""
from __future__ import annotations

import json
import uuid

from fastapi import Request
from psycopg2.extras import Json


def _ip(request: Request | None) -> str | None:
    return request.client.host if request and request.client else None


def audit(cur, *, actor, request: Request | None, action: str, entity_type: str,
          entity_id, before=None, after=None) -> None:
    """Use the caller's cursor so audit and business mutation commit together."""
    request_id = request.headers.get("x-request-id") if request else None
    cur.execute(
        "INSERT INTO audit_log (actor_user_id, actor_email, action, entity_type, entity_id, "
        "before, after, ip, request_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (str(actor["id"]) if actor and actor.get("id") else None,
         actor.get("email") if actor else None, action, entity_type, str(entity_id),
         Json(before) if before is not None else None, Json(after) if after is not None else None,
         _ip(request), request_id),
    )


def safe_metadata(**values):
    """Small explicit helper for PII-safe upload/action metadata."""
    return {key: value for key, value in values.items() if value is not None}
