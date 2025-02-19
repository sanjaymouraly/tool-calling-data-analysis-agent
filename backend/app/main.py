"""FastAPI application entry point."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import (
    routes_analysis,
    routes_datasets,
    routes_health,
    routes_reports,
    routes_settings,
    routes_tools,
)
from .core.config import settings
from .core.errors import AppError
from .core.logging import configure_logging, get_logger

configure_logging()
log = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    from .db.base import engine
    from .db.models import Base

    Base.metadata.create_all(bind=engine)
    log.info(
        "startup",
        version=settings.version,
        environment=settings.environment,
        database=settings.resolved_database_url.split("://")[0],
    )
    if settings.seed_demo_data_on_startup and settings.environment != "test":
        try:
            from .demo import seed

            created = seed.seed_demo_datasets(None)
            log.info("demo.seeded", datasets=created)
        except Exception as exc:  # pragma: no cover - demo data is best effort
            log.warning("demo.seed_failed", error=str(exc))
    yield
    log.info("shutdown")


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "Secure, evidence-backed business analytics. The language model may only select "
        "tools from a finite, validated library - it can never execute code, SQL, shell "
        "commands or file operations."
    ),
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=settings.allow_credentialed_cors,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed = int((time.perf_counter() - started) * 1000)
        log.error("request.failed", method=request.method, path=request.url.path, elapsed_ms=elapsed)
        raise
    elapsed = int((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        elapsed_ms=elapsed,
    )
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    log.warning("app_error", code=exc.code, message=exc.message, path=request.url.path)
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "http_error", "message": str(exc.detail), "details": {}}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "the request body or query parameters are invalid",
                "details": {"errors": exc.errors()[:10]},
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "an unexpected error occurred",
                "details": {},
            }
        },
    )


app.include_router(routes_health.router)
app.include_router(routes_datasets.router)
app.include_router(routes_analysis.router)
app.include_router(routes_tools.router)
app.include_router(routes_reports.router)
app.include_router(routes_settings.router)


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class SPAStaticFiles(StaticFiles):
    """Static files with single-page-application fallback.

    A request for a client-side route (``/workspace``) is answered with
    ``index.html`` so the React router can take over, while a missing asset
    or an unknown ``/api`` path still returns a proper 404.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith("api"):
                return await super().get_response("index.html", scope)
            raise


def mount_frontend() -> None:
    """Serve the built React application when it is available."""
    if FRONTEND_DIST.exists():
        app.mount("/", SPAStaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
        log.info("frontend.mounted", path=str(FRONTEND_DIST))
    else:
        log.info("frontend.not_built", expected=str(FRONTEND_DIST))


mount_frontend()
