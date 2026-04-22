from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AdminUser, Base
from app.db.session import get_db
from app.main import create_app
from app.services.auth_service import ADMIN_SESSION_COOKIE, clear_login_attempts, hash_admin_password


TEST_DATABASE_URL = "sqlite:///./data/test_auth_api.db"


def _build_test_engine():
    return create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})


def _build_test_session(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _build_auth_client(
    monkeypatch,
    seed_admin: bool = True,
    active: bool = True,
    seed_username: str = "admin",
    seed_display_name: str = "Admin User",
    seed_email: str = "admin@example.com",
    seed_role: str = "admin",
):
    monkeypatch.setenv("STOCK_SAGE_AUTH_DISABLED", "0")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-session-secret")
    clear_login_attempts("testclient")

    engine = _build_test_engine()
    TestingSessionLocal = _build_test_session(engine)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    if seed_admin:
        with TestingSessionLocal() as db:
            db.add(
                AdminUser(
                    username=seed_username,
                    display_name=seed_display_name,
                    email=seed_email,
                    role=seed_role,
                    password_hash=hash_admin_password("correct-password"),
                    active=active,
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
    return TestClient(app), app, engine


def _seed_account(
    engine,
    *,
    username: str,
    password: str,
    role: str,
    display_name: str,
    email: str,
    active: bool = True,
) -> None:
    TestingSessionLocal = _build_test_session(engine)
    with TestingSessionLocal() as db:
        db.add(
            AdminUser(
                username=username,
                display_name=display_name,
                email=email,
                role=role,
                password_hash=hash_admin_password(password),
                active=active,
            )
        )
        db.commit()


def _cleanup_auth_client(app, engine) -> None:
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_protected_routes_require_admin_login(monkeypatch) -> None:
    client, app, engine = _build_auth_client(monkeypatch)
    try:
        response = client.get("/products")

        assert response.status_code == 401
        assert response.json()["detail"] == "Admin login required."
    finally:
        _cleanup_auth_client(app, engine)


def test_admin_login_sets_session_cookie(monkeypatch) -> None:
    client, app, engine = _build_auth_client(monkeypatch)
    try:
        login_response = client.post(
            "/auth/login",
            json={"username": "admin", "password": "correct-password"},
        )
        me_response = client.get("/auth/me")

        assert login_response.status_code == 200
        assert login_response.json() == {
            "authenticated": True,
            "configured": True,
            "username": "admin",
            "display_name": "Admin User",
            "role": "admin",
        }
        assert client.cookies.get(ADMIN_SESSION_COOKIE)
        assert me_response.status_code == 200
        assert me_response.json() == {
            "authenticated": True,
            "configured": True,
            "username": "admin",
            "display_name": "Admin User",
            "role": "admin",
        }
    finally:
        _cleanup_auth_client(app, engine)


def test_admin_login_rejects_invalid_password(monkeypatch) -> None:
    client, app, engine = _build_auth_client(monkeypatch)
    try:
        response = client.post(
            "/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid admin credentials."
    finally:
        _cleanup_auth_client(app, engine)


def test_auth_status_reports_missing_admin_user(monkeypatch) -> None:
    client, app, engine = _build_auth_client(monkeypatch, seed_admin=False)
    try:
        response = client.get("/auth/me")

        assert response.status_code == 200
        assert response.json() == {
            "authenticated": False,
            "configured": False,
            "username": None,
            "display_name": None,
            "role": None,
        }
    finally:
        _cleanup_auth_client(app, engine)


def test_inactive_admin_cannot_login(monkeypatch) -> None:
    client, app, engine = _build_auth_client(monkeypatch, active=False)
    try:
        status_response = client.get("/auth/me")
        login_response = client.post(
            "/auth/login",
            json={"username": "admin", "password": "correct-password"},
        )

        assert status_response.json() == {
            "authenticated": False,
            "configured": False,
            "username": None,
            "display_name": None,
            "role": None,
        }
        assert login_response.status_code == 503
        assert login_response.json()["detail"] == "Admin authentication is not configured."
    finally:
        _cleanup_auth_client(app, engine)


def test_admin_cannot_manage_accounts(monkeypatch) -> None:
    client, app, engine = _build_auth_client(monkeypatch)
    try:
        login_response = client.post(
            "/auth/login",
            json={"username": "admin", "password": "correct-password"},
        )
        create_response = client.post(
            "/settings/accounts",
            json={
                "username": "staff",
                "display_name": "Staff Member",
                "email": "staff@example.com",
                "role": "staff",
                "password": "staff-password",
            },
        )

        assert login_response.status_code == 200
        assert create_response.status_code == 403
        assert create_response.json()["detail"] == "Super admin role required."
    finally:
        _cleanup_auth_client(app, engine)


def test_super_admin_can_create_admin_promote_demote_and_read_audit_logs(monkeypatch) -> None:
    client, app, engine = _build_auth_client(
        monkeypatch,
        seed_username="super_admin",
        seed_display_name="Super Admin",
        seed_email="super@example.com",
        seed_role="super_admin",
    )
    try:
        login_response = client.post(
            "/auth/login",
            json={"username": "super_admin", "password": "correct-password"},
        )
        create_admin_response = client.post(
            "/settings/accounts",
            json={
                "username": "manager",
                "display_name": "Manager Admin",
                "email": "manager@example.com",
                "role": "admin",
                "password": "manager-password",
            },
        )
        create_staff_response = client.post(
            "/settings/accounts",
            json={
                "username": "staff",
                "display_name": "Staff Member",
                "email": "staff@example.com",
                "role": "staff",
                "password": "staff-password",
            },
        )
        promote_response = client.patch(
            f"/settings/accounts/{create_staff_response.json()['id']}/role",
            json={"role": "admin"},
        )
        demote_response = client.patch(
            f"/settings/accounts/{create_admin_response.json()['id']}/role",
            json={"role": "staff"},
        )
        accounts_response = client.get("/settings/accounts")
        logs_response = client.get("/settings/audit-logs")

        assert login_response.status_code == 200
        assert create_admin_response.status_code == 201
        created_admin = create_admin_response.json()
        assert created_admin["username"] == "manager"
        assert created_admin["display_name"] == "Manager Admin"
        assert created_admin["email"] == "manager@example.com"
        assert created_admin["role"] == "admin"
        assert created_admin["status"] == "active"
        assert "password" not in created_admin
        assert create_staff_response.status_code == 201
        assert promote_response.status_code == 200
        assert promote_response.json()["role"] == "admin"
        assert demote_response.status_code == 200
        assert demote_response.json()["role"] == "staff"

        assert accounts_response.status_code == 200
        usernames = {account["username"] for account in accounts_response.json()}
        assert {"super_admin", "manager", "staff"}.issubset(usernames)

        assert logs_response.status_code == 200
        audit_actions = [entry["action"] for entry in logs_response.json()]
        assert "account.created" in audit_actions
        assert "account.role_updated" in audit_actions
    finally:
        _cleanup_auth_client(app, engine)


def test_super_admin_can_deactivate_admin_account(monkeypatch) -> None:
    client, app, engine = _build_auth_client(
        monkeypatch,
        seed_username="super_admin",
        seed_display_name="Super Admin",
        seed_email="super@example.com",
        seed_role="super_admin",
    )
    try:
        client.post("/auth/login", json={"username": "super_admin", "password": "correct-password"})
        create_admin_response = client.post(
            "/settings/accounts",
            json={
                "username": "manager",
                "display_name": "Manager Admin",
                "email": "manager@example.com",
                "role": "admin",
                "password": "manager-password",
            },
        )
        deactivate_response = client.delete(f"/settings/accounts/{create_admin_response.json()['id']}")

        assert create_admin_response.status_code == 201
        assert deactivate_response.status_code == 200
        assert deactivate_response.json()["username"] == "manager"
        assert deactivate_response.json()["status"] == "inactive"
    finally:
        _cleanup_auth_client(app, engine)


def test_admin_can_soft_delete_product_and_restore_from_recycle_bin(monkeypatch) -> None:
    client, app, engine = _build_auth_client(monkeypatch)
    try:
        client.post("/auth/login", json={"username": "admin", "password": "correct-password"})
        product_response = client.post(
            "/products",
            json={
                "sku": "SKU-RECYCLE-1",
                "name": "Recycle Bin Item",
                "category": "CPU",
                "cost_price": "1000.00",
                "sell_price": "1500.00",
                "reorder_min_qty": 1,
                "reorder_multiple": 1,
                "safety_stock": 0,
                "active": True,
                "initial_stock": 4,
            },
        )
        product_id = product_response.json()["id"]

        delete_response = client.delete(f"/products/{product_id}")
        list_response = client.get("/products")
        recycle_response = client.get("/settings/recycle-bin/products")
        logs_response = client.get("/settings/audit-logs")
        restore_response = client.post(f"/settings/recycle-bin/products/{product_id}/restore")
        restored_list_response = client.get("/products")

        assert product_response.status_code == 200
        assert delete_response.status_code == 200
        assert delete_response.json()["active"] is False
        assert all(product["id"] != product_id for product in list_response.json())

        assert recycle_response.status_code == 200
        recycled_products = recycle_response.json()
        assert [product["id"] for product in recycled_products] == [product_id]
        assert recycled_products[0]["active"] is False

        assert logs_response.status_code == 200
        audit_actions = [entry["action"] for entry in logs_response.json()]
        assert "product.deleted" in audit_actions

        assert restore_response.status_code == 200
        assert restore_response.json()["active"] is True
        assert any(product["id"] == product_id for product in restored_list_response.json())
    finally:
        _cleanup_auth_client(app, engine)


def test_staff_cannot_soft_delete_product(monkeypatch) -> None:
    client, app, engine = _build_auth_client(monkeypatch)
    try:
        client.post("/auth/login", json={"username": "admin", "password": "correct-password"})
        product_response = client.post(
            "/products",
            json={
                "sku": "SKU-STAFF-DELETE",
                "name": "Staff Delete Blocked",
                "category": "GPU",
                "cost_price": "2000.00",
                "sell_price": "2500.00",
                "reorder_min_qty": 1,
                "reorder_multiple": 1,
                "safety_stock": 0,
                "active": True,
                "initial_stock": 2,
            },
        )
        _seed_account(
            engine,
            username="staff",
            display_name="Staff Member",
            email="staff@example.com",
            role="staff",
            password="staff-password",
        )
        client.post("/auth/logout")
        staff_login_response = client.post(
            "/auth/login",
            json={"username": "staff", "password": "staff-password"},
        )
        delete_response = client.delete(f"/products/{product_response.json()['id']}")

        assert product_response.status_code == 200
        assert staff_login_response.status_code == 200
        assert delete_response.status_code == 403
        assert delete_response.json()["detail"] == "Admin role required."
    finally:
        _cleanup_auth_client(app, engine)


def test_staff_can_use_dashboard_routes_but_cannot_manage_settings(monkeypatch) -> None:
    client, app, engine = _build_auth_client(monkeypatch)
    try:
        _seed_account(
            engine,
            username="staff",
            display_name="Staff Member",
            email="staff@example.com",
            role="staff",
            password="staff-password",
        )

        staff_login_response = client.post(
            "/auth/login",
            json={"username": "staff", "password": "staff-password"},
        )
        products_response = client.get("/products")
        settings_response = client.get("/settings/accounts")

        assert staff_login_response.status_code == 200
        assert staff_login_response.json()["role"] == "staff"
        assert products_response.status_code == 200
        assert settings_response.status_code == 403
        assert settings_response.json()["detail"] == "Super admin role required."
    finally:
        _cleanup_auth_client(app, engine)
