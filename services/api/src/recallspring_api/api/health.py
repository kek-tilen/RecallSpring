from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .. import runtime
from ..config import get_settings
from ..db import new_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> JSONResponse:
    checks = {"database": False, "contracts": get_settings().schemas_dir.is_dir()}
    try:
        with new_session() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:  # noqa: BLE001 - readiness must report, not raise
        checks["database"] = False
    ok = all(checks.values())
    # The worker is reported, not checked: the API works without it (imports then wait in the queue).
    body = {"status": "ready" if ok else "not_ready", "checks": checks, "worker": runtime.worker_status()}
    return JSONResponse(body, status_code=200 if ok else 503)
