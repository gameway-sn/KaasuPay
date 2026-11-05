"""Loans and their repayment schedule (installments). All money in paise."""
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow
from app.models.user import User
from app.services.emi import repayment_schedule


class LoanStatus(StrEnum):
    APPLIED = "applied"      # just received (decided straight away)
    OFFERED = "offered"      # waiting for the customer to accept
    DECLINED = "declined"    # by the rules, or by the customer
    ACCEPTED = "accepted"    # waiting for finance to disburse
    DISBURSED = "disbursed"  # money sent, schedule created
    ACTIVE = "active"        # repayments started (Phase 4)
    CLOSED = "closed"        # fully repaid (Phase 4)


# A customer may have only one of these at a time.
OPEN_LOAN_STATUSES = (LoanStatus.OFFERED, LoanStatus.ACCEPTED, LoanStatus.DISBURSED, LoanStatus.ACTIVE)


class InstallmentStatus(StrEnum):
    DUE = "due"
    PAID = "paid"
    # "overdue" is not stored: it is worked out from the due date (see Installment.display_status).


class Loan(Base):
    __tablename__ = "loans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=LoanStatus.APPLIED, index=True)

    # What the customer typed
    requested_amount_paise: Mapped[int]
    tenure_months: Mapped[int]
    monthly_income_paise: Mapped[int]
    existing_emis_paise: Mapped[int]

    # What we decided
    annual_rate_percent: Mapped[int]
    offered_amount_paise: Mapped[int | None]
    emi_paise: Mapped[int | None]
    decision_reason: Mapped[str] = mapped_column(String(400), default="")

    applied_at: Mapped[datetime] = mapped_column(default=utcnow)
    decided_at: Mapped[datetime | None]
    accepted_at: Mapped[datetime | None]
    disbursed_at: Mapped[datetime | None]
    disbursed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime | None]

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    disbursed_by: Mapped[User | None] = relationship(foreign_keys=[disbursed_by_id])
    installments: Mapped[list["Installment"]] = relationship(
        back_populates="loan", cascade="all, delete-orphan", order_by="Installment.number"
    )

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_LOAN_STATUSES

    @property
    def total_payable_paise(self) -> int | None:
        """Sum of all installments (from the real schedule once it exists)."""
        if self.installments:
            return sum(i.amount_paise for i in self.installments)
        if self.offered_amount_paise:
            rows = repayment_schedule(self.offered_amount_paise, self.tenure_months, self.annual_rate_percent)
            return sum(row.amount_paise for row in rows)
        return None

    @property
    def outstanding_paise(self) -> int:
        return sum(i.amount_paise for i in self.installments if i.status == InstallmentStatus.DUE)


class Installment(Base):
    __tablename__ = "installments"
    __table_args__ = (UniqueConstraint("loan_id", "number", name="uq_installments_loan_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), index=True)
    number: Mapped[int]                 # 1, 2, 3, ...
    due_date: Mapped[date]
    amount_paise: Mapped[int]           # = principal + interest
    principal_paise: Mapped[int]
    interest_paise: Mapped[int]
    status: Mapped[str] = mapped_column(String(10), default=InstallmentStatus.DUE)

    loan: Mapped[Loan] = relationship(back_populates="installments")

    @property
    def is_overdue(self) -> bool:
        return self.status == InstallmentStatus.DUE and self.due_date < utcnow().date()

    @property
    def display_status(self) -> str:
        return "overdue" if self.is_overdue else self.status
