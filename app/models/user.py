"""The User table: customers and staff share one table, told apart by role."""
from datetime import datetime
from enum import StrEnum

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class Role(StrEnum):
    """Each staff role mirrors a department VLAN in the Packet Tracer network."""

    CUSTOMER = "customer"
    SUPPORT = "support"            # VLAN 20
    FINANCE = "finance"            # VLAN 10
    IT_ADMIN = "it_admin"          # VLAN 30
    BRANCH_AGENT = "branch_agent"  # VLAN 110


STAFF_ROLES = (Role.SUPPORT, Role.FINANCE, Role.IT_ADMIN, Role.BRANCH_AGENT)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default=Role.CUSTOMER)

    # argon2 hash, never the password itself. None = registration not finished.
    password_hash: Mapped[str | None] = mapped_column(String(255))

    phone_verified: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    # Login lockout (like `login block-for` on the routers): 5 wrong passwords -> 15 minutes.
    # server_default fills in 0 for users who already exist when the migration runs.
    failed_login_count: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None]

    @property
    def is_staff(self) -> bool:
        return self.role != Role.CUSTOMER

    @property
    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > utcnow()

    @property
    def home_url(self) -> str:
        """Where to send this user after login."""
        return "/staff" if self.is_staff else "/dashboard"
