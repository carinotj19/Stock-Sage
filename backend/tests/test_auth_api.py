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


def _build_auth_client(monkeypatch, seed_admin: bool = True, active: bool = True):
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
                    username="admin",
                    display_name="Admin User",
                    email="admin@example.com",
                    role="admin",
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


def test_admin_can_create_staff_account_and_read_audit_logs(monkeypatch) -> None:
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
        accounts_response = client.get("/settings/accounts")
        logs_response = client.get("/settings/audit-logs")

        assert login_response.status_code == 200
        assert create_response.status_code == 201
        created_account = create_response.json()
        assert created_account["username"] == "staff"
        assert created_account["display_name"] == "Staff Member"
        assert created_account["email"] == "staff@example.com"
        assert created_account["role"] == "staff"
        assert created_account["status"] == "active"
        assert "password" not in created_account

        assert accounts_response.status_code == 200
        usernames = {account["username"] for account in accounts_response.json()}
        assert {"admin", "staff"}.issubset(usernames)

        assert logs_response.status_code == 200
        audit_actions = [entry["action"] for entry in logs_response.json()]
        assert "account.created" in audit_actions
    finally:
        _cleanup_auth_client(app, engine)


def test_staff_can_use_dashboard_routes_but_cannot_manage_settings(monkeypatch) -> None:
    client, app, engine = _build_auth_client(monkeypatch)
    try:
        client.post("/auth/login", json={"username": "admin", "password": "correct-password"})
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
        assert create_response.status_code == 201
        client.post("/auth/logout")

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
        assert settings_response.json()["detail"] == "Admin role required."
    finally:
        _cleanup_auth_client(app, engine)
