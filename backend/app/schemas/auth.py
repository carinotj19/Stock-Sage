from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


UserRole = Literal["super_admin", "admin", "staff"]


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class AuthStatus(BaseModel):
    authenticated: bool
    configured: bool = True
    username: str | None = None
    display_name: str | None = None
    role: UserRole | None = None


class AccountCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    role: UserRole
    password: str = Field(min_length=8, max_length=256)


class AccountRoleUpdateRequest(BaseModel):
    role: Literal["admin", "staff"]


class AccountRead(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None = None
    role: UserRole
    status: Literal["active", "inactive"]
    created_at: datetime
    last_login_at: datetime | None = None


class AuditLogRead(BaseModel):
    id: int
    actor_username: str
    action: str
    target_type: str
    target_id: int | None = None
    message: str
    created_at: datetime


class SystemSettingsRead(BaseModel):
    auth_enabled: bool
    configured: bool
    active_accounts: int
    super_admin_accounts: int = 0
    admin_accounts: int
    staff_accounts: int
    session_ttl_seconds: int
