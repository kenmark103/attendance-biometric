"""Attendance System API — app factory, router wiring, startup.

Structure:
    app/core/      settings, DB, per-request auth (viewer/manager/admin deps)
    app/auth/      local passwords, Entra SSO, sessions, user admin, bootstrap, CLI
    app/routers/   attendance reads + bulk ingestion, WFH approvals
    app/ingestion/ COSEC biometric sync (untouched by the auth work)
"""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.auth.admin import router as admin_router
from app.auth.bootstrap import ensure_bootstrap_admin
from app.auth.local import router as local_router
from app.auth.microsoft import router as microsoft_router
from app.core import settings
from app.metrics.router import router as metrics_router
from app.routers.attendance import router as attendance_router
from app.routers.attendance_reads import router as attendance_reads_router
from app.routers.ingestion import router as ingestion_router
from app.routers.leave_import import router as leave_import_router
from app.routers.wfh import router as wfh_router

log = logging.getLogger(__name__)


class HealthOut(BaseModel):
    status: str
    auth_required: bool


class ReadyOut(BaseModel):
    status: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_startup()
    ensure_bootstrap_admin()
    try:
        from app.core.db import get_conn
        from app.leave.janitor import run_janitor
        conn = get_conn()
        try:
            run_janitor(conn)
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # janitor must never break startup
        log.warning(
            "leave janitor at startup skipped: %s: %s",
            type(exc).__name__,
            exc,
        )
    yield


app = FastAPI(title="Attendance System API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

app.include_router(local_router)
app.include_router(microsoft_router)
app.include_router(admin_router)
app.include_router(attendance_router)
app.include_router(attendance_reads_router)
app.include_router(ingestion_router)
app.include_router(leave_import_router)
app.include_router(wfh_router)
app.include_router(metrics_router)


@app.get("/health", response_model=HealthOut)
def health():
    return {"status": "ok", "auth_required": settings.AUTH_REQUIRED}


@app.get("/ready", response_model=ReadyOut)
def ready():
    """Readiness probe: confirms the API can reach its database."""
    from fastapi import HTTPException
    from app.core.db import get_conn

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
    except Exception:
        log.exception("readiness database check failed")
        raise HTTPException(status_code=503, detail="database_not_ready")
    finally:
        conn.close()
    return {"status": "ready"}
