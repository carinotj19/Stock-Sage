from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AdminUser, Base, InventoryBalance, SalesTransaction, StockMovement
from app.db.session import get_db
from app.main import create_app
from app.services.auth_service import clear_login_attempts, hash_admin_password


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
            "sold_at": "2026-02-02T10:30:00Z",
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

    sales_resp = client.get("/sales")
    assert sales_resp.status_code == 200
    sales_page = sales_resp.json()
    sales_rows = sales_page["items"]
    assert sales_page["total"] == 1
    assert sales_page["page"] == 1
    assert sales_page["page_size"] == 50
    assert sales_page["total_pages"] == 1
    assert len(sales_rows) == 1
    assert sales_rows[0]["receipt_no"] == "RCPT-001"
    assert sales_rows[0]["product_name"] == "Bread"
    assert sales_rows[0]["qty"] == 4
    assert sales_rows[0]["unit_sell_price"] == "2.00"
    assert sales_rows[0]["line_total"] == "8.00"

    filtered_sales_resp = client.get("/sales?date_from=2026-02-02&date_to=2026-02-02")
    assert filtered_sales_resp.status_code == 200
    assert filtered_sales_resp.json()["total"] == 1
    assert len(filtered_sales_resp.json()["items"]) == 1

    empty_sales_resp = client.get("/sales?date_from=2026-02-03")
    assert empty_sales_resp.status_code == 200
    assert empty_sales_resp.json()["total"] == 0
    assert empty_sales_resp.json()["items"] == []

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


def test_authenticated_sales_posting_does_not_conflict_with_auth_session_transaction(monkeypatch) -> None:
    monkeypatch.setenv("STOCK_SAGE_AUTH_DISABLED", "0")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-session-secret")
    clear_login_attempts("testclient")

    engine = _build_test_engine()
    TestingSessionLocal = _build_test_session(engine)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        db.add(
            AdminUser(
                username="admin",
                display_name="Admin User",
                email="admin@example.com",
                role="admin",
                password_hash=hash_admin_password("correct-password"),
                active=True,
            )
        )
        db.commit()

    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    login_resp = client.post("/auth/login", json={"username": "admin", "password": "correct-password"})
    supplier_resp = client.post(
        "/suppliers",
        json={"name": "Authenticated Supplier", "lead_time_days_default": 4},
    )
    product_resp = client.post(
        "/products",
        json={
            "sku": "SKU-AUTH-SALES-1",
            "name": "Authenticated Sale Item",
            "supplier_id": supplier_resp.json()["id"],
            "cost_price": "1.00",
            "sell_price": "2.00",
            "initial_stock": 5,
        },
    )
    sale_resp = client.post(
        "/sales",
        json={
            "receipt_no": "AUTH-RCPT-001",
            "payment_method": "cash",
            "items": [{"product_id": product_resp.json()["id"], "qty": 2}],
        },
    )

    assert login_resp.status_code == 200
    assert supplier_resp.status_code == 200
    assert product_resp.status_code == 200
    assert sale_resp.status_code == 200
    assert sale_resp.json()["total_amount"] == "4.00"

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
