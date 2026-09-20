import logging
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.routes_auth import router as auth_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_inventory import router as inventory_router
from app.api.routes_prices import router as prices_router
from app.api.routes_sales import router as sales_router
from app.api.routes_settings import router as settings_router
from app.db.session import init_db
from app.services.auth_service import require_authenticated_user


logger = logging.getLogger(__name__)


class TrustedWriteOriginMiddleware:
    UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = set(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method", "").upper() in self.UNSAFE_METHODS:
            headers = {key.lower(): value for key, value in scope.get("headers", [])}
            raw_origin = headers.get(b"origin")
            if raw_origin:
                origin = raw_origin.decode("latin-1").strip().rstrip("/")
                if origin not in self.allowed_origins:
                    response = JSONResponse({"detail": "Origin is not allowed."}, status_code=403)
                    await response(scope, receive, send)
                    return

        await self.app(scope, receive, send)


class UnhandledExceptionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except Exception:
            logger.exception("unhandled_backend_error")
            response = JSONResponse(
                {"detail": "Backend request failed. Check Render logs for unhandled_backend_error."},
                status_code=500,
            )
            await response(scope, receive, send)


def _parse_cors_allow_origins(value: str) -> list[str]:
    origins: list[str] = []
    for raw_origin in value.split(","):
        origin = raw_origin.strip().strip("\"'").rstrip("/")
        if origin and origin not in origins:
            origins.append(origin)
    return origins


def create_app() -> FastAPI:
    app = FastAPI(title="Stock Sage API")
    cors_allow_origins = os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    origins = _parse_cors_allow_origins(cors_allow_origins)
    app.add_middleware(UnhandledExceptionMiddleware)
    app.add_middleware(TrustedWriteOriginMiddleware, allowed_origins=origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def startup() -> None:
        init_db()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    protected_dependencies = [Depends(require_authenticated_user)]
    app.include_router(auth_router)
    app.include_router(settings_router)
    app.include_router(inventory_router, dependencies=protected_dependencies)
    app.include_router(sales_router, dependencies=protected_dependencies)
    app.include_router(dashboard_router, dependencies=protected_dependencies)
    app.include_router(prices_router, dependencies=protected_dependencies)
    return app


app = create_app()
