"""Loan actions: apply, accept/decline an offer (customer), disburse (finance).

applied -> offered | declined -> accepted -> disbursed -> active -> closed
(active and closed are reached by repayments in Phase 4.)
"""
import calendar
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import (
    OPEN_LOAN_STATUSES, Installment, KycStatus, Loan, LoanStatus, User,
)
from app.schemas.loans import LoanApplicationForm
from app.services.decision import decide
from app.services.emi import ANNUAL_RATE_PERCENT, repayment_schedule
from app.services.kyc import get_kyc
from app.services.money import rupees_to_paise


class LoanStateError(Exception):
    """The action isn't allowed in the loan's current state."""


def get_open_loan(db: Session, user_id: int) -> Loan | None:
    return db.scalars(
        select(Loan).where(Loan.user_id == user_id, Loan.status.in_(OPEN_LOAN_STATUSES))
    ).first()


def get_customer_loans(db: Session, user_id: int) -> list[Loan]:
    return list(db.scalars(select(Loan).where(Loan.user_id == user_id).order_by(Loan.id.desc())))


def get_customer_loan(db: Session, user: User, loan_id: int) -> Loan | None:
    """The loan, but only if it belongs to this customer. Otherwise None (the route shows 404)."""
    loan = db.get(Loan, loan_id)
    if loan is None or loan.user_id != user.id:
        return None
    return loan


def apply_for_loan(db: Session, user: User, form: LoanApplicationForm) -> Loan:
    if get_open_loan(db, user.id):
        raise LoanStateError("You already have an open loan or offer. Finish or decline it first.")

    kyc = get_kyc(db, user.id)
    loan = Loan(
        user_id=user.id,
        status=LoanStatus.APPLIED,
        requested_amount_paise=rupees_to_paise(form.amount),
        tenure_months=form.tenure_months,
        monthly_income_paise=rupees_to_paise(form.monthly_income),
        existing_emis_paise=rupees_to_paise(form.existing_emis),
        annual_rate_percent=ANNUAL_RATE_PERCENT,
    )
    db.add(loan)

    decision = decide(
        kyc_approved=kyc is not None and kyc.status == KycStatus.APPROVED,
        amount_paise=loan.requested_amount_paise,
        months=loan.tenure_months,
        monthly_income_paise=loan.monthly_income_paise,
        existing_emis_paise=loan.existing_emis_paise,
        annual_rate_percent=loan.annual_rate_percent,
    )
    loan.status = LoanStatus.OFFERED if decision.offered else LoanStatus.DECLINED
    loan.offered_amount_paise = decision.amount_paise
    loan.emi_paise = decision.emi_paise
    loan.decision_reason = decision.reason
    loan.decided_at = utcnow()
    db.commit()
    return loan


def _require(loan: Loan, status: LoanStatus) -> None:
    if loan.status != status:
        raise LoanStateError(f"This loan is {loan.status}, so that action isn't possible.")


def accept_offer(db: Session, loan: Loan) -> None:
    _require(loan, LoanStatus.OFFERED)
    loan.status = LoanStatus.ACCEPTED
    loan.accepted_at = utcnow()
    db.commit()


def decline_offer(db: Session, loan: Loan) -> None:
    _require(loan, LoanStatus.OFFERED)
    loan.status = LoanStatus.DECLINED
    loan.decision_reason = "You declined this offer."
    db.commit()


def add_months(start: date, months: int) -> date:
    """Same day of the month, `months` later. 31 Jan + 1 month = 28/29 Feb."""
    years, month_index = divmod(start.month - 1 + months, 12)
    year, month = start.year + years, month_index + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def disburse(db: Session, loan: Loan, staff: User) -> None:
    """Finance releases the money: create the repayment schedule."""
    _require(loan, LoanStatus.ACCEPTED)
    today = utcnow().date()
    for row in repayment_schedule(loan.offered_amount_paise, loan.tenure_months, loan.annual_rate_percent):
        loan.installments.append(Installment(
            number=row.number,
            due_date=add_months(today, row.number),  # first EMI one month after disbursal
            amount_paise=row.amount_paise,
            principal_paise=row.principal_paise,
            interest_paise=row.interest_paise,
        ))
    loan.status = LoanStatus.DISBURSED
    loan.disbursed_at = utcnow()
    loan.disbursed_by_id = staff.id
    db.commit()
