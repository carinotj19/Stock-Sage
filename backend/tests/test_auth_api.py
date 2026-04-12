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
        assert login_response.json() == {"authenticated": True, "configured": True, "username": "admin"}
        assert client.cookies.get(ADMIN_SESSION_COOKIE)
        assert me_response.status_code == 200
        assert me_response.json() == {"authenticated": True, "configured": True, "username": "admin"}
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
        assert response.json() == {"authenticated": False, "configured": False, "username": None}
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

        assert status_response.json() == {"authenticated": False, "configured": False, "username": None}
        assert login_response.status_code == 503
        assert login_response.json()["detail"] == "Admin authentication is not configured."
    finally:
        _cleanup_auth_client(app, engine)
