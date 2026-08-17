"""Composition root e configuracao do adaptador FastAPI."""

from __future__ import annotations

import os
import secrets
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from fastapi_app.adapters.inbound.http import router, templates
from fastapi_app.domain import (
    ApplicationError,
    ConflictError,
    ForbiddenError,
    ImportUnavailableError,
    InvalidInputError,
    NotFoundError,
    ProcessingError,
)
from fastapi_app.infrastructure.container import build_container
from fastapi_app.application.ports import AssistantPort


SERVICE_ROOT = Path(__file__).resolve().parent.parent
if configured_private_root := os.environ.get("PRIVATE_ROOT"):
    DEFAULT_PRIVATE_ROOT = Path(configured_private_root).resolve()
else:
    local_root = (
        SERVICE_ROOT.parent.parent
        if SERVICE_ROOT.parent.name == "services"
        else SERVICE_ROOT
    )
    DEFAULT_PRIVATE_ROOT = (local_root / "private").resolve()
ERROR_STATUS = {
    ForbiddenError: 403,
    InvalidInputError: 400,
    NotFoundError: 409,
    ConflictError: 409,
    ProcessingError: 422,
    ImportUnavailableError: 503,
}


def _session_key(private_root: Path) -> str:
    path = private_root / "secrets" / "web-session.key"
    if path.exists():
        key = path.read_bytes()
        if len(key) != 32:
            raise RuntimeError("invalid session key")
        return key.hex()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    with path.open("xb") as output:
        output.write(key)
    return key.hex()


def _local_date(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime(
            "%d/%m/%Y %H:%M"
        )
    except ValueError:
        return "-"


def _request_id(request: Request) -> str:
    candidate = request.headers.get("X-Request-ID", "")
    try:
        return str(uuid.UUID(candidate))
    except ValueError:
        return str(uuid.uuid4())


def create_app(private_root: Path | None = None, testing: bool = False, categorization_repository: object | None = None, cash_flow_repository: object | None = None, assistant: AssistantPort | None = None) -> FastAPI:
    selected_private_root = (
        private_root.resolve() if private_root is not None else DEFAULT_PRIVATE_ROOT
    )
    selected_private_root.mkdir(parents=True, exist_ok=True)
    container = build_container(selected_private_root, categorization_repository, cash_flow_repository, assistant)
    app = FastAPI(title="Fatura Local", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.container = container
    # Alias temporario para consumidores locais que usavam o antigo Model MVC.
    app.state.store = container.repository
    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_key(selected_private_root),
        same_site="strict",
        https_only=False,
    )
    templates.env.filters["local_date"] = _local_date
    app.mount(
        "/static",
        StaticFiles(directory=SERVICE_ROOT / "fastapi_app" / "views" / "static"),
        name="static",
    )
    app.include_router(router)
    docker_mode = os.environ.get("WEB_DOCKER_MODE") == "1"

    @app.middleware("http")
    async def local_security_and_audit(request: Request, call_next):
        request_id = _request_id(request)
        request.state.request_id = request_id
        request_context = container.audit.bind_request(request_id)
        started = time.perf_counter()
        remote = request.client.host if request.client else None
        host = request.url.hostname or ""
        allowed_remote = docker_mode or testing or remote in {None, "127.0.0.1", "::1"}
        if not allowed_remote or host not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "testserver",
        }:
            response = JSONResponse(
                {"error": "A aplicacao aceita apenas conexoes locais."}, 403
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                container.audit.emit(
                    "http.request", level="error", request_id=request_id,
                    method=request.method, http_status=500,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    outcome="unhandled_error",
                )
                container.audit.reset_request(request_context)
                raise
        route = request.scope.get("route")
        route_pattern = getattr(route, "path", "unmatched")
        try:
            container.audit.emit(
                "http.request",
                level="warning" if response.status_code >= 400 else "info",
                request_id=request_id,
                method=request.method,
                route=route_pattern,
                http_status=response.status_code,
                duration_ms=(time.perf_counter() - started) * 1000,
                outcome="completed",
            )
            response.headers["X-Request-ID"] = request_id
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'"
            )
            return response
        finally:
            container.audit.reset_request(request_context)

    @app.exception_handler(ApplicationError)
    async def application_error(_request: Request, error: ApplicationError):
        status = next(
            (value for error_type, value in ERROR_STATUS.items() if isinstance(error, error_type)),
            500,
        )
        return JSONResponse({"error": error.public_message, "code": error.code}, status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        return JSONResponse({"error": "Dados da requisicao invalidos."}, 422)

    return app
