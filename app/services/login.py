"""Checking a login, with lockout. Rule: 5 wrong passwords -> locked for 15 minutes.

While locked, even the RIGHT password is refused. That is what stops an
attacker trying thousands of passwords. A successful login resets the count.
"""
from datetime import timedelta
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import User
from app.security import verify_password
from app.services.audit import record
from app.services.crypto import mask_phone

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15


class LoginResult(Enum):
    OK = "ok"
    BAD = "bad"          # wrong phone or password (we don't say which)
    LOCKED = "locked"


def attempt_login(db: Session, phone: str, password: str) -> tuple[LoginResult, User | None]:
    phone = phone.strip()
    user = db.scalars(select(User).where(User.phone == phone)).first()
    target = {"target_type": "user", "target_id": user.id} if user else {}

    if user is not None and user.is_locked:
        record(db, None, "auth.login_blocked", detail=f"phone {mask_phone(phone)} is locked", **target)
        db.commit()
        return LoginResult.LOCKED, user

    password_ok = verify_password(password, user.password_hash if user else None)

    if user is None or not password_ok or not user.is_active:
        result = LoginResult.BAD
        if user is not None and not password_ok:
            user.failed_login_count += 1
            if user.failed_login_count >= MAX_FAILED_LOGINS:
                user.locked_until = utcnow() + timedelta(minutes=LOCK_MINUTES)
                user.failed_login_count = 0
                record(db, None, "auth.locked",
                       detail=f"{MAX_FAILED_LOGINS} wrong passwords: locked for {LOCK_MINUTES} min", **target)
                result = LoginResult.LOCKED
        record(db, None, "auth.login_failed", detail=f"phone {mask_phone(phone) if phone else '(empty)'}", **target)
        db.commit()
        return result, user

    user.failed_login_count = 0
    user.locked_until = None
    record(db, user, "auth.login", target_type="user", target_id=user.id)
    db.commit()
    return LoginResult.OK, user
