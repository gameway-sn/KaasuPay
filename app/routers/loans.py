"""Loan pages.

Customer:  GET/POST /loans/apply           apply (decided straight away)
           GET      /loans/{id}             my loan: offer, decision, schedule
           POST     /loans/{id}/accept|decline
Finance:   GET      /staff/loans            loan book + simple report
           GET      /staff/loans/{id}       one loan
           POST     /staff/loans/{id}/disburse
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import Installment, InstallmentStatus, KycStatus, Loan, LoanStatus, Role, User
from app.schemas.common import error_messages
from app.schemas.loans import LoanApplicationForm
from app.services.kyc import get_kyc
from app.services.loans import (
    LoanStateError, accept_offer, apply_for_loan, decline_offer, disburse,
    get_customer_loan, get_open_loan,
)
from app.templating import render

router = APIRouter()


# ======================= Customer side =======================

def _apply_page(request, user, db, form=None, errors=None, status_code=200):
    kyc = get_kyc(db, user.id)
    return render(request, "loans/apply.html", {
        "user": user,
        "kyc_approved": kyc is not None and kyc.status == KycStatus.APPROVED,
        "open_loan": get_open_loan(db, user.id),
        "form": form or {},
        "errors": errors or [],
    }, status_code=status_code)


# Declared before /loans/{loan_id} so "apply" is never read as a loan id.
@router.get("/loans/apply")
def apply_page(
    request: Request,
    user: User = Depends(require_role(Role.CUSTOMER)),
    db: Session = Depends(get_db),
):
    return _apply_page(request, user, db)


@router.post("/loans/apply")
def apply_submit(
    request: Request,
    amount: str = Form(""),
    tenure_months: str = Form(""),
    monthly_income: str = Form(""),
    existing_emis: str = Form("0"),
    user: User = Depends(require_role(Role.CUSTOMER)),
    db: Session = Depends(get_db),
):
    typed = {"amount": amount, "tenure_months": tenure_months,
             "monthly_income": monthly_income, "existing_emis": existing_emis or "0"}
    try:
        form = LoanApplicationForm(**typed)
    except ValidationError as exc:
        return _apply_page(request, user, db, typed, error_messages(exc), 422)
    try:
        loan = apply_for_loan(db, user, form)
    except LoanStateError as exc:
        return _apply_page(request, user, db, typed, [str(exc)], 409)
    return RedirectResponse(f"/loans/{loan.id}", status_code=303)


def _my_loan(db: Session, user: User, loan_id: int) -> Loan:
    loan = get_customer_loan(db, user, loan_id)
    if loan is None:
        # Someone else's loan looks exactly like a loan that doesn't exist.
        raise HTTPException(404, "No such loan.")
    return loan


@router.get("/loans/{loan_id}")
def loan_page(
    request: Request,
    loan_id: int,
    user: User = Depends(require_role(Role.CUSTOMER)),
    db: Session = Depends(get_db),
):
    return render(request, "loans/detail.html", {"user": user, "loan": _my_loan(db, user, loan_id)})


@router.post("/loans/{loan_id}/accept")
def loan_accept(
    loan_id: int,
    user: User = Depends(require_role(Role.CUSTOMER)),
    db: Session = Depends(get_db),
):
    try:
        accept_offer(db, _my_loan(db, user, loan_id))
    except LoanStateError as exc:
        raise HTTPException(409, str(exc)) from None
    return RedirectResponse(f"/loans/{loan_id}", status_code=303)


@router.post("/loans/{loan_id}/decline")
def loan_decline(
    loan_id: int,
    user: User = Depends(require_role(Role.CUSTOMER)),
    db: Session = Depends(get_db),
):
    try:
        decline_offer(db, _my_loan(db, user, loan_id))
    except LoanStateError as exc:
        raise HTTPException(409, str(exc)) from None
    return RedirectResponse(f"/loans/{loan_id}", status_code=303)


# ======================= Finance side =======================

@router.get("/staff/loans")
def loan_book(
    request: Request,
    user: User = Depends(require_role(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    counts = dict(db.execute(select(Loan.status, func.count()).group_by(Loan.status)).all())
    disbursed_total = db.scalar(
        select(func.coalesce(func.sum(Loan.offered_amount_paise), 0))
        .where(Loan.status.in_([LoanStatus.DISBURSED, LoanStatus.ACTIVE, LoanStatus.CLOSED]))
    )
    outstanding_total = db.scalar(
        select(func.coalesce(func.sum(Installment.amount_paise), 0))
        .where(Installment.status == InstallmentStatus.DUE)
    )
    awaiting = db.scalars(
        select(Loan).where(Loan.status == LoanStatus.ACCEPTED).order_by(Loan.accepted_at)
    ).all()
    all_loans = db.scalars(select(Loan).order_by(Loan.id.desc()).limit(100)).all()
    return render(request, "staff/loan_book.html", {
        "user": user,
        "statuses": list(LoanStatus),
        "counts": counts,
        "disbursed_total": disbursed_total,
        "outstanding_total": outstanding_total,
        "awaiting": awaiting,
        "loans": all_loans,
    })


def _any_loan(db: Session, loan_id: int) -> Loan:
    loan = db.get(Loan, loan_id)
    if loan is None:
        raise HTTPException(404, "No such loan.")
    return loan


@router.get("/staff/loans/{loan_id}")
def staff_loan_page(
    request: Request,
    loan_id: int,
    user: User = Depends(require_role(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    return render(request, "staff/loan_detail.html", {"user": user, "loan": _any_loan(db, loan_id)})


@router.post("/staff/loans/{loan_id}/disburse")
def staff_disburse(
    loan_id: int,
    user: User = Depends(require_role(Role.FINANCE)),  # support, IT, branch -> 403
    db: Session = Depends(get_db),
):
    try:
        disburse(db, _any_loan(db, loan_id), user)
    except LoanStateError as exc:
        raise HTTPException(409, str(exc)) from None
    return RedirectResponse(f"/staff/loans/{loan_id}", status_code=303)
