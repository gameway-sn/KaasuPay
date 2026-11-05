"""Create one demo staff account per role. Safe to run more than once.

Run (after `alembic upgrade head`):  python -m app.seed

All data here is fake. The password comes from SEED_STAFF_PASSWORD in .env.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Role, User
from app.security import hash_password

DEMO_STAFF = [
    ("9000000001", "Demo Support Officer", Role.SUPPORT),
    ("9000000002", "Demo Finance Officer", Role.FINANCE),
    ("9000000003", "Demo IT Admin", Role.IT_ADMIN),
    ("9000000004", "Demo Branch Agent", Role.BRANCH_AGENT),
]


def seed_staff(db: Session) -> list[str]:
    """Add any demo staff that don't exist yet. Returns the phones added."""
    added = []
    for phone, name, role in DEMO_STAFF:
        if db.scalars(select(User).where(User.phone == phone)).first():
            continue
        db.add(User(
            phone=phone,
            full_name=name,
            role=role,
            password_hash=hash_password(settings.seed_staff_password),
            phone_verified=True,
        ))
        added.append(phone)
    db.commit()
    return added


def main() -> None:
    with SessionLocal() as db:
        added = seed_staff(db)
    print(f"Added {len(added)} staff account(s). Demo staff logins:")
    for phone, name, role in DEMO_STAFF:
        print(f"  {role:<13} phone {phone}  ({name})")
    print("Password for all of them: the SEED_STAFF_PASSWORD value in your .env")


if __name__ == "__main__":
    main()
