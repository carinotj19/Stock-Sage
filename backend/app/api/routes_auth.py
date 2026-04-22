from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.auth import AdminLoginRequest, AuthStatus
from app.services.auth_service import (
    ADMIN_SESSION_COOKIE,
    clear_login_attempts,
    create_session_token,
    get_cookie_samesite,
    get_cookie_secure,
    get_request_session_admin,
    get_user_display_name,
    get_session_ttl_seconds,
    is_auth_configured,
    is_auth_disabled,
    is_login_allowed,
    record_admin_login,
    record_failed_login,
    verify_admin_credentials,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _auth_status_for_account(account) -> AuthStatus:
    return AuthStatus(
        authenticated=True,
        configured=True,
        username=account.username,
        display_name=get_user_display_name(account),
        role=account.role,
    )


@router.get("/me", response_model=AuthStatus)
def get_auth_status(request: Request, db: Session = Depends(get_db)) -> AuthStatus:
    if is_auth_disabled():
        return AuthStatus(
            authenticated=True,
            configured=True,
            username="super_admin",
            display_name="Super Admin",
            role="super_admin",
        )

    if not is_auth_configured(db):
        return AuthStatus(authenticated=False, configured=False)

    admin = get_request_session_admin(request, db)
    if admin is None:
        return AuthStatus(authenticated=False, configured=True)
    return _auth_status_for_account(admin)


@router.post("/login", response_model=AuthStatus)
def login(
    payload: AdminLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AuthStatus:
    if not is_auth_configured(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured.",
        )

    client_key = _client_key(request)
    if not is_login_allowed(client_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
        )

    admin = verify_admin_credentials(db, payload.username, payload.password)
    if admin is None:
        record_failed_login(client_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin credentials.")

    clear_login_attempts(client_key)
    record_admin_login(db, admin)
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=create_session_token(admin),
        httponly=True,
        secure=get_cookie_secure(),
        samesite=get_cookie_samesite(),
        max_age=get_session_ttl_seconds(),
        path="/",
    )
    return _auth_status_for_account(admin)


@router.post("/logout", response_model=AuthStatus)
def logout(response: Response, db: Session = Depends(get_db)) -> AuthStatus:
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE,
        httponly=True,
        secure=get_cookie_secure(),
        samesite=get_cookie_samesite(),
        path="/",
    )
    return AuthStatus(authenticated=False, configured=is_auth_configured(db))
