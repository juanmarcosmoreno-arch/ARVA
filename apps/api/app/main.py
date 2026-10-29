import json
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.api.capacity import UploadCapacityGuard, insufficient_storage_response
from app.api.metadata_limit import MetadataUploadLimit
from app.api.request_context import HEADER, RequestContext, route_of
from app.api.routes import (
    amr,
    analyses,
    annotations,
    assemblies,
    dashboard,
    databases,
    diagnostics,
    explorer,
    files,
    imports,
    metadata,
    mlst,
    mobile_elements,
    overview,
    projects,
    reports,
    samples,
    species,
    system,
    tools,
)
from app.api.storage_guard import StorageGuard, storage_unavailable_response
from app.core import errorlog
from app.core.config import get_settings
from app.services import locations, startup
from app.services.capacity import InsufficientStorageError
from app.services.import_roots import ImportPathError
from app.storage.local import StoragePathError


class _EscapingJSONResponse(JSONResponse):
    """Escapes lone surrogates (echoed invalid input such as "\\udcff") instead of failing with a 500."""

    def render(self, content) -> bytes:
        try:
            return super().render(content)
        except UnicodeEncodeError:
            return json.dumps(content, allow_nan=False, separators=(",", ":")).encode("ascii")


# The English text of the 500 response; the interface has it as api.error.internal_error.
INTERNAL_ERROR = ("ARVA hit an unexpected error (error ID {error_id}). Copy the error details to report it: they "
                  "say what happened without any of your data (Settings → Diagnostics).")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # A data folder used for the first time gets its storage marker now; a missing or foreign one is reported here
    # and refused at every write.
    try:
        locations.ensure_data()
    except locations.StorageUnavailable as exc:
        errorlog.record("api", "warning", exc.code, str(exc), params=exc.params)
    errorlog.info("startup", "API started", **startup.summary())
    if get_settings().startup_checks:
        threading.Thread(target=startup.check, name="arva-startup-checks", daemon=True).start()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ARVA API",
        description="ARVA — Integrated Genomic Discovery Platform. From sequence to insight.",
        version=__version__,
        lifespan=lifespan,
    )
    # Added before CORS so that CORS stays outermost and also wraps the 507 and 503 responses; the storage guard is
    # outside the capacity checks, so that a missing disk is reported as such rather than as a lack of space.
    app.add_middleware(UploadCapacityGuard, api_prefix=settings.api_v1_prefix)
    app.add_middleware(MetadataUploadLimit, api_prefix=settings.api_v1_prefix)
    app.add_middleware(StorageGuard, api_prefix=settings.api_v1_prefix)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", HEADER],
    )
    app.add_middleware(RequestContext)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        """Any error no other handler names: kept in the error log with the request's route (never its values),
        and the entry's id returned so that the interface can show it."""
        cid = request.scope.get("state", {}).get("correlation_id")
        route = route_of(request.scope)
        error_id = await run_in_threadpool(
            errorlog.record, "api", "error", "internal_error", params={"method": request.method, "route": route},
            exc=exc, request={"method": request.method, "route": route, "status": 500}, correlation_id=cid)
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            content={"detail": INTERNAL_ERROR.format(error_id=error_id), "code": "internal_error",
                                     "params": {"error_id": error_id}, "error_id": error_id},
                            headers={HEADER: cid} if cid else None)

    @app.exception_handler(StoragePathError)
    @app.exception_handler(ImportPathError)
    async def storage_path_error(_: Request, exc: ValueError):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return _EscapingJSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": jsonable_encoder(exc.errors())}
        )

    @app.exception_handler(InsufficientStorageError)
    async def insufficient_storage(_: Request, exc: InsufficientStorageError):
        return insufficient_storage_response(exc)

    @app.exception_handler(locations.StorageUnavailable)
    async def storage_unavailable(_: Request, exc: locations.StorageUnavailable):
        return storage_unavailable_response(exc)

    @app.get("/health", tags=["system"])
    def health():
        """Always 200 while the API runs (the container health check); "degraded" when the data folder cannot be
        written now, with the reason in `storage` (Settings → Storage explains it)."""
        storage = locations.health()
        return {"status": "ok" if storage in ("ok", "new") else "degraded", "version": __version__,
                "storage": storage}

    for module in (dashboard, projects, samples, files, imports, metadata, analyses, tools, reports, overview,
                   assemblies, annotations, explorer, amr, mobile_elements, databases, mlst, species, system,
                   diagnostics):
        app.include_router(module.router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
