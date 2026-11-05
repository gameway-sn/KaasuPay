"""Recording EMI payments (online by the customer, cash by a branch agent).

Rules:
- Only disbursed/active loans take payments.
- EMIs are paid in order: only the next unpaid installment.
- The form says WHICH installment it is paying. If that one is already paid
  (double click, two tabs), we refuse instead of quietly paying the next one.
- Cash must match the EMI exactly.
- First payment: disbursed -> active. Last payment: -> closed.
"""
import secrets

from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import InstallmentStatus, Loan, LoanStatus, Payment, PaymentMethod, User
from app.services.audit import record
from app.services.money import format_inr


class PaymentError(Exception):
    """The payment was refused. The message is safe to show to the user."""


class AmountMismatch(PaymentError):
    """Cash received is not exactly the EMI (a typing mistake, so 422 rather than 409)."""


def fake_gateway_charge(amount_paise: int) -> str:
    """Pretend to charge the customer through a payment gateway.

    DEMO ONLY: always succeeds and no money moves. A real app would call a
    gateway here (Razorpay test mode is a stretch goal) and check its reply.
    """
    return f"DEMO-ONLINE-{secrets.token_hex(4).upper()}"


def record_payment(
    db: Session,
    loan: Loan,
    installment_id: int,
    method: PaymentMethod,
    recorded_by: User,
    amount_paise: int | None = None,
) -> Payment:
    if loan.status not in (LoanStatus.DISBURSED, LoanStatus.ACTIVE):
        raise PaymentError(f"This loan is {loan.status}, so it isn't taking payments.")

    installment = loan.next_installment
    if installment is None:
        raise PaymentError("Every installment on this loan is already paid.")
    if installment.id != installment_id:
        raise PaymentError(
            "That installment is already paid or isn't the next one due. Refresh the page and try again."
        )
    if amount_paise is not None and amount_paise != installment.amount_paise:
        raise AmountMismatch(
            f"Amount received {format_inr(amount_paise)} does not match "
            f"EMI #{installment.number} of {format_inr(installment.amount_paise)}."
        )

    if method == PaymentMethod.ONLINE:
        reference = fake_gateway_charge(installment.amount_paise)
    else:
        reference = f"DEMO-CASH-{secrets.token_hex(4).upper()}"

    payment = Payment(
        amount_paise=installment.amount_paise,
        method=method,
        reference=reference,
        recorded_by=recorded_by,
    )
    # Attach through the relationships so loan.payments / installment.payment update at once.
    loan.payments.append(payment)
    installment.payment = payment
    installment.status = InstallmentStatus.PAID

    if loan.next_installment is None:
        loan.status = LoanStatus.CLOSED
        loan.closed_at = utcnow()
    elif loan.status == LoanStatus.DISBURSED:
        loan.status = LoanStatus.ACTIVE

    record(db, recorded_by, f"payment.{method}", target_type="loan", target_id=loan.id,
           customer_id=loan.user_id,
           detail=f"EMI #{installment.number} {format_inr(installment.amount_paise)} ref {reference}"
                  + (" (loan closed)" if loan.status == LoanStatus.CLOSED else ""))
    db.commit()
    return payment
