"""FastAPI entry point.

Run (from backend/):  uv run uvicorn app.main:app --reload --port 8000
API docs:             http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, ProgrammingError
from starlette.exceptions import HTTPException

from app.config import get_settings
from app.db import engine
from app.llm.errors import LLMError
from app.llm.tracing import init_tracing, shutdown_tracing
from app.permissions import PermissionDenied
from app.routers import ai, auth, data, health, portal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("app")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_tracing(settings)
    yield
    shutdown_tracing()
    await engine.dispose()


app = FastAPI(title="LMS GenAI", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (health.router, auth.router, portal.router, data.router, ai.router):
    app.include_router(r)


# --- Error handling: every error leaves the API as {"error": code, "message": text} ---


def _error(status: int, code: str, message: str, detail: str | None = None) -> JSONResponse:
    body = {"error": code, "message": message}
    if detail and settings.app_env == "dev":
        body["detail"] = detail  # technical info only in dev, never in production
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return _error(exc.status_code, f"http_{exc.status_code}", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    return _error(422, "invalid_input", "Some input is missing or invalid.", str(exc.errors())[:500])


@app.exception_handler(PermissionDenied)
async def permission_denied(_: Request, exc: PermissionDenied):
    return _error(403, "forbidden", exc.message)


@app.exception_handler(LLMError)
async def llm_error(_: Request, exc: LLMError):
    return _error(exc.http_status, exc.code, exc.user_message, exc.detail)


@app.exception_handler(ProgrammingError)
async def db_schema_error(_: Request, exc: ProgrammingError):
    if "does not exist" in str(exc):
        return _error(
            500, "db_not_seeded", "Database tables are missing. Run: uv run python -m app.seed --reset", str(exc)[:300]
        )
    log.exception("Database error")
    return _error(500, "db_error", "A database error occurred.", str(exc)[:300])


@app.exception_handler(OperationalError)
async def db_down(_: Request, exc: OperationalError):
    return _error(503, "db_unavailable", "Cannot reach Postgres. Is `docker compose up -d` running?", str(exc)[:300])


@app.exception_handler(Exception)
async def unexpected(_: Request, exc: Exception):
    log.exception("Unhandled error")
    return _error(500, "internal_error", "Something went wrong on the server.", f"{type(exc).__name__}: {exc}"[:300])
