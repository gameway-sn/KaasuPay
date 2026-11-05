"""The payments ledger: one row per EMI paid, online or in cash.

Finance's totals, the customer's receipts and (in Phase 5) the audit trail
all read from this one table, whoever took the money.
"""
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow
from app.models.loan import Installment, Loan
from app.models.user import User


class PaymentMethod(StrEnum):
    ONLINE = "online"  # customer, through the fake gateway
    CASH = "cash"      # branch agent, at the counter


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), index=True)
    # unique: the database itself refuses a second payment for the same installment.
    installment_id: Mapped[int] = mapped_column(ForeignKey("installments.id"), unique=True)
    amount_paise: Mapped[int]
    method: Mapped[str] = mapped_column(String(10))
    reference: Mapped[str] = mapped_column(String(40), unique=True)  # e.g. DEMO-ONLINE-4F2A91C3
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # customer or branch agent
    paid_at: Mapped[datetime] = mapped_column(default=utcnow)

    loan: Mapped[Loan] = relationship(back_populates="payments")
    installment: Mapped[Installment] = relationship(back_populates="payment")
    recorded_by: Mapped[User] = relationship()
