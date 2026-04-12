from datetime import UTC, datetime
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AdminUser
from app.db.session import get_db


ADMIN_SESSION_COOKIE = "stock_sage_admin_session"
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 600_000
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}


class AuthNotConfiguredError(RuntimeError):
    pass


def is_auth_disabled() -> bool:
    return os.getenv("STOCK_SAGE_AUTH_DISABLED", "").lower() in {"1", "true", "yes"}


def _get_int_env(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def get_session_ttl_seconds() -> int:
    return _get_int_env("ADMIN_SESSION_TTL_SECONDS", 86400, 300)


def get_cookie_samesite() -> str:
    value = os.getenv("ADMIN_COOKIE_SAMESITE", "lax").lower()
    return value if value in {"lax", "strict", "none"} else "lax"


def get_cookie_secure() -> bool:
    return os.getenv("ADMIN_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}


def normalize_username(username: str) -> str:
    return username.strip().lower()


def hash_admin_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS)
    return (
        f"{PASSWORD_HASH_ALGORITHM}${PASSWORD_HASH_ITERATIONS}$"
        f"{_base64_url_encode(salt)}${_base64_url_encode(digest)}"
    )


def verify_admin_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        iterations = int(iterations_text)
    except ValueError:
        return False

    if algorithm != PASSWORD_HASH_ALGORITHM or iterations <= 0:
        return False

    try:
        salt = _base64_url_decode(salt_text)
        expected_digest = _base64_url_decode(digest_text)
    except ValueError:
        return False

    actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual_digest, expected_digest)


def get_active_admin_by_username(db: Session, username: str) -> AdminUser | None:
    return db.scalars(
        select(AdminUser).where(
            AdminUser.username == normalize_username(username),
            AdminUser.active.is_(True),
        )
    ).first()


def has_active_admin(db: Session) -> bool:
    return (
        db.scalars(select(AdminUser.id).where(AdminUser.active.is_(True)).limit(1)).first()
        is not None
    )


def is_auth_configured(db: Session) -> bool:
    return bool(os.getenv("ADMIN_SESSION_SECRET")) and has_active_admin(db)


def _get_session_secret() -> bytes:
    secret = os.getenv("ADMIN_SESSION_SECRET")
    if not secret:
        raise AuthNotConfiguredError("ADMIN_SESSION_SECRET is not configured.")
    return secret.encode("utf-8")


def _base64_url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64_url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _sign(value: str) -> str:
    digest = hmac.new(_get_session_secret(), value.encode("ascii"), hashlib.sha256).digest()
    return _base64_url_encode(digest)


def verify_admin_credentials(db: Session, username: str, password: str) -> AdminUser | None:
    admin = get_active_admin_by_username(db, username)
    if admin is None or not verify_admin_password(password, admin.password_hash):
        return None
    return admin


def create_session_token(admin: AdminUser) -> str:
    payload = {
        "sub": admin.id,
        "username": admin.username,
        "exp": int(time.time()) + get_session_ttl_seconds(),
    }
    encoded_payload = _base64_url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{encoded_payload}.{_sign(encoded_payload)}"


def get_session_admin(db: Session, token: str | None) -> AdminUser | None:
    if not token or "." not in token:
        return None

    encoded_payload, signature = token.rsplit(".", 1)
    expected_signature = _sign(encoded_payload)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload: Any = json.loads(_base64_url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    expires_at = payload.get("exp")
    admin_id = payload.get("sub")
    if not isinstance(expires_at, int) or expires_at < int(time.time()):
        return None
    if not isinstance(admin_id, int):
        return None

    return db.scalars(
        select(AdminUser).where(
            AdminUser.id == admin_id,
            AdminUser.active.is_(True),
        )
    ).first()


def get_request_session_admin(request: Request, db: Session) -> AdminUser | None:
    if is_auth_disabled():
        return AdminUser(id=0, username="admin", password_hash="", active=True)
    if not is_auth_configured(db):
        return None
    return get_session_admin(db, request.cookies.get(ADMIN_SESSION_COOKIE))


def require_admin(request: Request, db: Session = Depends(get_db)) -> None:
    if is_auth_disabled():
        return

    if not is_auth_configured(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured.",
        )

    if get_request_session_admin(request, db) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin login required.",
        )


def record_admin_login(db: Session, admin: AdminUser) -> None:
    admin.last_login_at = datetime.now(UTC)
    db.add(admin)
    db.commit()


def is_login_allowed(client_key: str) -> bool:
    now = time.time()
    window_seconds = _get_int_env("ADMIN_LOGIN_WINDOW_SECONDS", 300, 60)
    max_attempts = _get_int_env("ADMIN_LOGIN_MAX_ATTEMPTS", 10, 1)
    attempts = [timestamp for timestamp in _LOGIN_ATTEMPTS.get(client_key, []) if now - timestamp <= window_seconds]
    _LOGIN_ATTEMPTS[client_key] = attempts
    return len(attempts) < max_attempts


def record_failed_login(client_key: str) -> None:
    _LOGIN_ATTEMPTS.setdefault(client_key, []).append(time.time())


def clear_login_attempts(client_key: str) -> None:
    _LOGIN_ATTEMPTS.pop(client_key, None)
