"""The audit log: an append-only record of who did what, to whose data.

The app's version of `show logging` on the routers. Rows can be added, never changed
or deleted, and that's enforced twice:
  1. in Python (SQLAlchemy events below), and
  2. in the database (SQLite triggers), so even raw SQL is refused.
"""
from datetime import datetime

from sqlalchemy import DDL, ForeignKey, String, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow
from app.models.user import User


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    # Who did it (None = not logged in, e.g. a failed login).
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(20))

    action: Mapped[str] = mapped_column(String(40), index=True)  # e.g. "kyc.view", "loan.disburse"
    target_type: Mapped[str | None] = mapped_column(String(20))  # "kyc", "loan", "user", "path"
    target_id: Mapped[int | None]
    # Whose personal data or money this was about, so we can answer
    # "who looked at Asha's KYC?" with one filter.
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    detail: Mapped[str] = mapped_column(String(300), default="")
    ip: Mapped[str | None] = mapped_column(String(45))

    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id])
    customer: Mapped[User | None] = relationship(foreign_keys=[customer_id])


class AuditTamperError(Exception):
    """Someone tried to change or delete an audit row."""


@event.listens_for(AuditEvent, "before_update")
def _refuse_update(mapper, connection, target):
    raise AuditTamperError("The audit log is append-only: events cannot be changed.")


@event.listens_for(AuditEvent, "before_delete")
def _refuse_delete(mapper, connection, target):
    raise AuditTamperError("The audit log is append-only: events cannot be deleted.")


# Database-level guard. The same SQL is in the Alembic migration for the real database;
# this copy makes `create_all` (used by the tests) add the triggers too.
NO_UPDATE_TRIGGER = (
    "CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events "
    "BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END"
)
NO_DELETE_TRIGGER = (
    "CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events "
    "BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END"
)
event.listen(AuditEvent.__table__, "after_create", DDL(NO_UPDATE_TRIGGER).execute_if(dialect="sqlite"))
event.listen(AuditEvent.__table__, "after_create", DDL(NO_DELETE_TRIGGER).execute_if(dialect="sqlite"))
