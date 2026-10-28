import json

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.capacity import UploadCapacityGuard, insufficient_storage_response
from app.api.metadata_limit import MetadataUploadLimit
from app.api.routes import (
    analyses,
    dashboard,
    files,
    imports,
    metadata,
    overview,
    projects,
    reports,
    samples,
    system,
    tools,
)
from app.core.config import get_settings
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


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ARVA API",
        description="ARVA — Integrated Genomic Discovery Platform. From Sequence to Discovery.",
        version=__version__,
    )
    # Added before CORS so that CORS stays outermost and also wraps the 507 responses.
    app.add_middleware(UploadCapacityGuard, api_prefix=settings.api_v1_prefix)
    app.add_middleware(MetadataUploadLimit, api_prefix=settings.api_v1_prefix)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

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

    @app.get("/health", tags=["system"])
    def health():
        return {"status": "ok", "version": __version__}

    for module in (dashboard, projects, samples, files, imports, metadata, analyses, tools, reports, overview,
                   system):
        app.include_router(module.router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
