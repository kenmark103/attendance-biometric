"""Attendance System API — app factory, router wiring, startup.

Structure:
    app/core/      settings, DB, per-request auth (viewer/manager/admin deps)
    app/auth/      local passwords, Entra SSO, sessions, user admin, bootstrap, CLI
    app/routers/   attendance reads + bulk ingestion, WFH approvals
    app/ingestion/ COSEC biometric sync (untouched by the auth work)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth.admin import router as admin_router
from app.auth.bootstrap import ensure_bootstrap_admin
from app.auth.local import router as local_router
from app.auth.microsoft import router as microsoft_router
from app.core import settings
from app.metrics.router import router as metrics_router
from app.routers.attendance import router as attendance_router
from app.routers.ingestion import router as ingestion_router
from app.routers.leave_import import router as leave_import_router
from app.routers.wfh import router as wfh_router


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
        print(f"leave janitor at startup skipped: {type(exc).__name__}: {exc}")
    yield


app = FastAPI(title="Attendance System API", lifespan=lifespan)
# Same-origin by design (browser reaches the API through the nginx /api
# prefix): no CORS middleware, no cross-site cookies.

app.include_router(local_router)
app.include_router(microsoft_router)
app.include_router(admin_router)
app.include_router(attendance_router)
app.include_router(ingestion_router)
app.include_router(leave_import_router)
app.include_router(wfh_router)
app.include_router(metrics_router)


@app.get("/health")
def health():
    return {"status": "ok", "auth_required": settings.AUTH_REQUIRED}
