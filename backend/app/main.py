from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_inventory import router as inventory_router
from app.api.routes_prices import router as prices_router
from app.api.routes_sales import router as sales_router
from app.db.session import init_db


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

    app.include_router(inventory_router)
    app.include_router(sales_router)
    app.include_router(dashboard_router)
    app.include_router(prices_router)
    return app


app = create_app()
