"""IT admin actions on staff accounts. Every one is written to the audit log.

- Only staff accounts can be managed here (customers: 404).
- An admin can't deactivate their own account (no locking yourself out).
- New and reset passwords are random and shown to the admin ONCE.
"""
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Role, User
from app.schemas.admin import StaffCreateForm
from app.security import hash_password
from app.services.audit import record


class StaffAdminError(Exception):
    """The action isn't allowed. The message is safe to show."""


def temporary_password() -> str:
    """e.g. 'q3Xv-8LmTzA9': 12 random characters, from `secrets` (safe for passwords)."""
    return secrets.token_urlsafe(9)


def list_staff(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.role != Role.CUSTOMER).order_by(User.role, User.full_name)))


def get_staff(db: Session, user_id: int) -> User | None:
    user = db.get(User, user_id)
    if user is None or user.role == Role.CUSTOMER:
        return None
    return user


def create_staff(db: Session, admin: User, form: StaffCreateForm) -> tuple[User, str]:
    if db.scalars(select(User).where(User.phone == form.phone)).first():
        raise StaffAdminError("That phone number already has an account.")
    password = temporary_password()
    staff = User(phone=form.phone, full_name=form.full_name, role=form.role,
                 password_hash=hash_password(password), phone_verified=True)
    db.add(staff)
    db.flush()  # gives staff an id for the audit line
    record(db, admin, "admin.staff_create", target_type="user", target_id=staff.id,
           detail=f"{staff.full_name} as {staff.role}")
    db.commit()
    return staff, password


def set_active(db: Session, admin: User, staff: User, active: bool) -> None:
    if staff.id == admin.id and not active:
        raise StaffAdminError("You can't deactivate your own account.")
    staff.is_active = active
    record(db, admin, "admin.staff_activate" if active else "admin.staff_deactivate",
           target_type="user", target_id=staff.id, detail=staff.full_name)
    db.commit()


def unlock(db: Session, admin: User, staff: User) -> None:
    staff.locked_until = None
    staff.failed_login_count = 0
    record(db, admin, "admin.staff_unlock", target_type="user", target_id=staff.id, detail=staff.full_name)
    db.commit()


def reset_password(db: Session, admin: User, staff: User) -> str:
    password = temporary_password()
    staff.password_hash = hash_password(password)
    staff.locked_until = None
    staff.failed_login_count = 0
    record(db, admin, "admin.password_reset", target_type="user", target_id=staff.id, detail=staff.full_name)
    db.commit()
    return password
