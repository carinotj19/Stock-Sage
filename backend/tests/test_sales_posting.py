from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, InventoryBalance, SalesTransaction, StockMovement
from app.db.session import get_db
from app.main import create_app


TEST_DATABASE_URL = "sqlite:///./data/test_sales_posting.db"


def _build_test_engine():
    return create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})


def _build_test_session(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def test_sales_posting_is_atomic_with_stock_movements() -> None:
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
        json={"name": "Supplier S", "lead_time_days_default": 4},
    )
    supplier_id = supplier_resp.json()["id"]

    product_resp = client.post(
        "/products",
        json={
            "sku": "SKU-SALES-1",
            "name": "Bread",
            "supplier_id": supplier_id,
            "cost_price": "1.00",
            "sell_price": "2.00",
            "initial_stock": 10,
        },
    )
    product_id = product_resp.json()["id"]

    ok_sale_resp = client.post(
        "/sales",
        json={
            "receipt_no": "RCPT-001",
            "payment_method": "cash",
            "items": [{"product_id": product_id, "qty": 4}],
        },
    )
    assert ok_sale_resp.status_code == 200
    assert ok_sale_resp.json()["total_amount"] == "8.00"

    with TestingSessionLocal() as db:
        balance = db.get(InventoryBalance, product_id)
        assert balance is not None
        assert balance.on_hand_qty == 6

        transaction_count = db.scalar(select(func.count()).select_from(SalesTransaction))
        assert transaction_count == 1

        movement_rows = db.scalars(
            select(StockMovement).where(StockMovement.product_id == product_id, StockMovement.movement_type == "sale")
        ).all()
        assert len(movement_rows) == 1
        assert movement_rows[0].qty_delta == -4

    bad_sale_resp = client.post(
        "/sales",
        json={
            "receipt_no": "RCPT-002",
            "payment_method": "cash",
            "items": [{"product_id": product_id, "qty": 100}],
        },
    )
    assert bad_sale_resp.status_code == 400
    assert "Insufficient stock" in bad_sale_resp.json()["detail"]

    with TestingSessionLocal() as db:
        balance = db.get(InventoryBalance, product_id)
        assert balance is not None
        assert balance.on_hand_qty == 6

        transaction_count = db.scalar(select(func.count()).select_from(SalesTransaction))
        assert transaction_count == 1

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
