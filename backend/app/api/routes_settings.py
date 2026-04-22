from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AdminUser, AuditLog
from app.db.session import get_db
from app.schemas.auth import AccountCreateRequest, AccountRead, AccountRoleUpdateRequest, AuditLogRead, SystemSettingsRead
from app.schemas.inventory import ProductRead
from app.services.auth_service import (
    get_session_ttl_seconds,
    get_user_display_name,
    hash_admin_password,
    is_auth_configured,
    is_auth_disabled,
    normalize_optional_email,
    normalize_username,
    record_audit_log,
    require_admin,
    require_super_admin,
)
from app.services.inventory_service import InventoryService


router = APIRouter(prefix="/settings", tags=["settings"])


def _account_read(account: AdminUser) -> AccountRead:
    return AccountRead(
        id=account.id,
        username=account.username,
        display_name=get_user_display_name(account),
        email=account.email,
        role=account.role,
        status="active" if account.active else "inactive",
        created_at=account.created_at,
        last_login_at=account.last_login_at,
    )


def _audit_log_read(log: AuditLog) -> AuditLogRead:
    return AuditLogRead(
        id=log.id,
        actor_username=log.actor_username,
        action=log.action,
        target_type=log.target_type,
        target_id=log.target_id,
        message=log.message,
        created_at=log.created_at,
    )


@router.get("/system", response_model=SystemSettingsRead)
def get_system_settings(
    _: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SystemSettingsRead:
    active_accounts = db.scalar(select(func.count()).select_from(AdminUser).where(AdminUser.active.is_(True))) or 0
    admin_accounts = (
        db.scalar(
            select(func.count()).select_from(AdminUser).where(AdminUser.active.is_(True), AdminUser.role == "admin")
        )
        or 0
    )
    super_admin_accounts = (
        db.scalar(
            select(func.count())
            .select_from(AdminUser)
            .where(AdminUser.active.is_(True), AdminUser.role == "super_admin")
        )
        or 0
    )
    staff_accounts = (
        db.scalar(
            select(func.count()).select_from(AdminUser).where(AdminUser.active.is_(True), AdminUser.role == "staff")
        )
        or 0
    )
    return SystemSettingsRead(
        auth_enabled=not is_auth_disabled(),
        configured=is_auth_configured(db),
        active_accounts=active_accounts,
        super_admin_accounts=super_admin_accounts,
        admin_accounts=admin_accounts,
        staff_accounts=staff_accounts,
        session_ttl_seconds=get_session_ttl_seconds(),
    )


@router.get("/accounts", response_model=list[AccountRead])
def list_accounts(
    _: AdminUser = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> list[AccountRead]:
    accounts = db.scalars(select(AdminUser).order_by(AdminUser.created_at.desc(), AdminUser.username.asc())).all()
    return [_account_read(account) for account in accounts]


@router.post("/accounts", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreateRequest,
    actor: AdminUser = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> AccountRead:
    username = normalize_username(payload.username)
    if not username:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Username is required.")

    email = normalize_optional_email(payload.email)
    existing_username = db.scalars(select(AdminUser.id).where(AdminUser.username == username)).first()
    if existing_username is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists.")

    if email is not None:
        existing_email = db.scalars(select(AdminUser.id).where(func.lower(AdminUser.email) == email)).first()
        if existing_email is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists.")

    account = AdminUser(
        username=username,
        display_name=payload.display_name.strip(),
        email=email,
        role=payload.role,
        password_hash=hash_admin_password(payload.password),
        active=True,
    )
    db.add(account)
    db.flush()
    record_audit_log(
        db,
        actor=actor,
        action="account.created",
        target_type="account",
        target_id=account.id,
        message=f"Created {payload.role} account {username}.",
    )
    db.commit()
    db.refresh(account)
    return _account_read(account)


@router.patch("/accounts/{account_id}/role", response_model=AccountRead)
def update_account_role(
    account_id: int,
    payload: AccountRoleUpdateRequest,
    actor: AdminUser = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> AccountRead:
    account = db.get(AdminUser, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    if account.role == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Super admin accounts cannot be promoted or demoted.",
        )
    if account.role == payload.role:
        return _account_read(account)

    previous_role = account.role
    account.role = payload.role
    db.add(account)
    record_audit_log(
        db,
        actor=actor,
        action="account.role_updated",
        target_type="account",
        target_id=account.id,
        message=f"Changed account {account.username} from {previous_role} to {payload.role}.",
    )
    db.commit()
    db.refresh(account)
    return _account_read(account)


@router.delete("/accounts/{account_id}", response_model=AccountRead)
def deactivate_account(
    account_id: int,
    actor: AdminUser = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> AccountRead:
    account = db.get(AdminUser, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    if account.id == actor.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account.")

    if account.active and account.role == "super_admin":
        active_super_admins = (
            db.scalar(
                select(func.count())
                .select_from(AdminUser)
                .where(AdminUser.active.is_(True), AdminUser.role == "super_admin")
            )
            or 0
        )
        if active_super_admins <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one super admin account is required.",
            )

    account.active = False
    db.add(account)
    record_audit_log(
        db,
        actor=actor,
        action="account.deactivated",
        target_type="account",
        target_id=account.id,
        message=f"Deactivated account {account.username}.",
    )
    db.commit()
    db.refresh(account)
    return _account_read(account)


@router.get("/audit-logs", response_model=list[AuditLogRead])
def list_audit_logs(
    _: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditLogRead]:
    logs = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)).all()
    return [_audit_log_read(log) for log in logs]


@router.get("/recycle-bin/products", response_model=list[ProductRead])
def list_recycled_products(
    _: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[ProductRead]:
    service = InventoryService(db)
    return service.list_recycled_products()


@router.post("/recycle-bin/products/{product_id}/restore", response_model=ProductRead)
def restore_recycled_product(
    product_id: int,
    actor: AdminUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProductRead:
    service = InventoryService(db)
    return service.restore_product(product_id, actor)
