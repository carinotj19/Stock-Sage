from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from app.api.routes_auth import router as auth_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_inventory import router as inventory_router
from app.api.routes_prices import router as prices_router
from app.api.routes_sales import router as sales_router
from app.api.routes_settings import router as settings_router
from app.db.session import init_db
from app.services.auth_service import require_authenticated_user


def create_app() -> FastAPI:
    app = FastAPI(title="Stock Sage API")
    cors_allow_origins = os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    origins = [origin.strip() for origin in cors_allow_origins.split(",") if origin.strip()]
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
