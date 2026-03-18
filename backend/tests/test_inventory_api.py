from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base
from app.db.session import get_db
from app.main import create_app


TEST_DATABASE_URL = "sqlite:///./data/test_inventory_api.db"


def _build_test_engine():
    return create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})


def _build_test_session(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def test_inventory_crud_and_adjustment() -> None:
    engine = _build_test_engine()
    TestingSessionLocal = _build_test_session(engine)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    supplier_resp = client.post(
        "/suppliers",
        json={
            "name": "Supplier A",
            "contact_name": "Alice",
            "phone": "12345",
            "email": "alice@example.com",
            "lead_time_days_default": 5,
        },
    )
    assert supplier_resp.status_code == 200
    supplier_id = supplier_resp.json()["id"]

    product_resp = client.post(
        "/products",
        json={
            "sku": "SKU-100",
            "name": "Milk",
            "category": "Dairy",
            "supplier_id": supplier_id,
            "cost_price": "2.20",
            "sell_price": "3.50",
            "reorder_min_qty": 5,
            "reorder_multiple": 5,
            "safety_stock": 3,
            "active": True,
            "initial_stock": 10,
        },
    )
    assert product_resp.status_code == 200
    product_data = product_resp.json()
    assert product_data["sku"] == "SKU-100"
    assert product_data["on_hand_qty"] == 10
    product_id = product_data["id"]

    list_resp = client.get("/products")
    assert list_resp.status_code == 200
    products = list_resp.json()
    assert len(products) == 1
    assert products[0]["name"] == "Milk"

    adjust_resp = client.post(
        "/inventory/adjust",
        json={
            "product_id": product_id,
            "qty_delta": -3,
            "reason": "damaged",
            "reference_type": "manual",
        },
    )
    assert adjust_resp.status_code == 200
    assert adjust_resp.json()["on_hand_qty"] == 7

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

