"""The native executor's endpoints (ARVA.app on the user's Mac; app.services.native, docs/plan-flye-nativo.md,
"Contrato implementado"). Every request needs the token ARVA.app wrote ("Authorization: Bearer <token>"); these
routes do not use the session-based access control (ARVA.app has no account), and nothing in them is project data.
Request bodies refuse unknown fields, so an argument vector can never be sent where none is expected."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.schemas import (
    NativeClaimRequest,
    NativeExecutorRegister,
    NativeFinishRequest,
    NativeHeartbeatRequest,
)
from app.services import native


def require_token(authorization: str | None = Header(default=None)) -> None:
    native.check_token(authorization)


router = APIRouter(prefix="/native", tags=["native executor"], dependencies=[Depends(require_token)])
# Read by the interface (Settings → Performance, the Flye dialog): guarded like every other route (app.main).
status_router = APIRouter(tags=["native executor"])


def native_error_response(_: Request, exc: native.NativeError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": str(exc), "code": exc.code, "params": exc.params})


@router.post("/executor")
def register(payload: NativeExecutorRegister, db: Session = Depends(get_db)):
    """Register ARVA.app's executor, or renew its registration (every register_seconds): its version, the Mac, its
    data folder and storage id, and per tool the facts arva_tools/native.py printed. Answers, per tool, whether it may
    run jobs (and why not), with the intervals to use."""
    return native.register(db, payload.model_dump(mode="json"))


@router.post("/jobs/claim")
def claim(payload: NativeClaimRequest, db: Session = Depends(get_db)):
    """The oldest job waiting for this executor, with an exclusive lease and its work record; 204 when none."""
    taken = native.claim(db, payload.executor_id, list(payload.tools))
    return Response(status_code=status.HTTP_204_NO_CONTENT) if taken is None else taken


@router.post("/jobs/{job_id}/heartbeat")
def heartbeat(job_id: str, payload: NativeHeartbeatRequest, db: Session = Depends(get_db)):
    """Renew the lease (within lease_seconds of the last one). cancel: true means stop the tool and finish with
    outcome "stopped". 409 native_lease_lost: the lease expired or is another's; stop the tool."""
    return native.heartbeat(db, job_id, payload.executor_id, payload.lease_id, payload.pid)


@router.post("/jobs/{job_id}/finish")
def finish(job_id: str, payload: NativeFinishRequest):
    """The final report (what arva_tools/native.py `run` printed). Refused unless its argv is the one ARVA built."""
    return native.finish(job_id, payload.executor_id, payload.lease_id, payload.report.model_dump(mode="json"))


@status_router.get("/system/native-executor")
def executor_status():
    """Whether ARVA.app's native executor is known and open, and the Flye it can run (version, build, lock)."""
    return native.status()
