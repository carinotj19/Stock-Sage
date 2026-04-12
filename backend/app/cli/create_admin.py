import argparse
from getpass import getpass

from sqlalchemy import select

from app.db.models import AdminUser
from app.db.session import SessionLocal, init_db
from app.services.auth_service import hash_admin_password, normalize_username


def _read_password(password_arg: str | None) -> str:
    if password_arg is not None:
        return password_arg

    password = getpass("Admin password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    return password


def create_or_update_admin(username: str, password: str, reset_password: bool = False) -> AdminUser:
    normalized_username = normalize_username(username)
    if not normalized_username:
        raise ValueError("Username is required.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")

    init_db()
    with SessionLocal() as db:
        admin = db.scalars(select(AdminUser).where(AdminUser.username == normalized_username)).first()
        if admin and not reset_password:
            raise ValueError(f"Admin user '{normalized_username}' already exists. Use --reset-password to update it.")

        password_hash = hash_admin_password(password)
        if admin:
            admin.password_hash = password_hash
            admin.active = True
            db.add(admin)
            action = "updated"
        else:
            admin = AdminUser(username=normalized_username, password_hash=password_hash, active=True)
            db.add(admin)
            action = "created"

        db.commit()
        db.refresh(admin)
        print(f"Admin user '{admin.username}' {action}.")
        return admin


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or reset a Stock Sage admin user.")
    parser.add_argument("--username", default="admin", help="Admin username to create or update.")
    parser.add_argument("--password", help="Password value. Omit to enter it securely.")
    parser.add_argument("--reset-password", action="store_true", help="Reset password if the admin already exists.")
    args = parser.parse_args()

    try:
        password = _read_password(args.password)
        create_or_update_admin(args.username, password, reset_password=args.reset_password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
