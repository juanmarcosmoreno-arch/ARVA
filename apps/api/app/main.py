from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import analyses, dashboard, files, projects, reports, samples, tools
from app.core.config import get_settings
from app.storage.local import StoragePathError


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ARVA API",
        description="ARVA — Integrated Genomic Discovery Platform. From Sequence to Discovery.",
        version=__version__,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    @app.exception_handler(StoragePathError)
    async def storage_path_error(_: Request, exc: StoragePathError):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})

    @app.get("/health", tags=["system"])
    def health():
        return {"status": "ok", "version": __version__}

    for module in (dashboard, projects, samples, files, analyses, tools, reports):
        app.include_router(module.router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
