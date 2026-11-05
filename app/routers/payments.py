"""Paying EMIs.

Customer:      GET/POST /loans/{id}/pay          fake payment gateway (online)
Branch agent:  GET      /staff/collect?loan_id=  find a loan by its ID
               POST     /staff/collect/{id}      record a cash EMI
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import Loan, PaymentMethod, Role, User
from app.services.crypto import mask_phone
from app.services.loans import get_customer_loan
from app.services.money import parse_amount_paise
from app.services.payments import AmountMismatch, PaymentError, record_payment
from app.templating import render

router = APIRouter()


# ======================= Customer: online =======================

def _my_loan(db: Session, user: User, loan_id: int) -> Loan:
    loan = get_customer_loan(db, user, loan_id)
    if loan is None:
        raise HTTPException(404, "No such loan.")
    return loan


@router.get("/loans/{loan_id}/pay")
def gateway_page(
    request: Request,
    loan_id: int,
    user: User = Depends(require_role(Role.CUSTOMER)),
    db: Session = Depends(get_db),
):
    loan = _my_loan(db, user, loan_id)
    if loan.next_installment is None:
        return RedirectResponse(f"/loans/{loan_id}", status_code=303)
    return render(request, "payments/gateway.html",
                  {"user": user, "loan": loan, "installment": loan.next_installment})


@router.post("/loans/{loan_id}/pay")
def gateway_pay(
    loan_id: int,
    installment_id: int = Form(...),
    user: User = Depends(require_role(Role.CUSTOMER)),
    db: Session = Depends(get_db),
):
    loan = _my_loan(db, user, loan_id)
    try:
        record_payment(db, loan, installment_id, PaymentMethod.ONLINE, recorded_by=user)
    except PaymentError as exc:
        raise HTTPException(409, str(exc)) from None
    return RedirectResponse(f"/loans/{loan_id}?paid=1", status_code=303)


# ======================= Branch agent: cash =======================

def _collect_page(request, user, loan=None, searched=None, errors=None, done=False, status_code=200):
    return render(request, "staff/collect.html", {
        "user": user,
        "loan": loan,
        "searched": searched,
        "masked_phone": mask_phone(loan.user.phone) if loan else None,
        "errors": errors or [],
        "done": done,
    }, status_code=status_code)


@router.get("/staff/collect")
def collect_page(
    request: Request,
    loan_id: str = "",
    done: bool = False,
    user: User = Depends(require_role(Role.BRANCH_AGENT)),
    db: Session = Depends(get_db),
):
    loan_id = loan_id.strip().lstrip("#")
    if not loan_id:
        return _collect_page(request, user)
    if not loan_id.isascii() or not loan_id.isdigit():
        return _collect_page(request, user, searched=loan_id,
                             errors=["A loan ID is a number, like 7."], status_code=422)
    loan = db.get(Loan, int(loan_id))
    if loan is None:
        return _collect_page(request, user, searched=loan_id,
                             errors=[f"There is no loan #{loan_id}."], status_code=404)
    return _collect_page(request, user, loan=loan, searched=loan_id, done=done)


@router.post("/staff/collect/{loan_id}")
def collect_cash(
    request: Request,
    loan_id: int,
    installment_id: int = Form(...),
    amount: str = Form(""),
    user: User = Depends(require_role(Role.BRANCH_AGENT)),
    db: Session = Depends(get_db),
):
    loan = db.get(Loan, loan_id)
    if loan is None:
        raise HTTPException(404, "No such loan.")
    try:
        amount_paise = parse_amount_paise(amount)
    except ValueError as exc:
        return _collect_page(request, user, loan=loan, searched=str(loan_id), errors=[str(exc)], status_code=422)
    try:
        record_payment(db, loan, installment_id, PaymentMethod.CASH, recorded_by=user, amount_paise=amount_paise)
    except AmountMismatch as exc:
        return _collect_page(request, user, loan=loan, searched=str(loan_id), errors=[str(exc)], status_code=422)
    except PaymentError as exc:
        return _collect_page(request, user, loan=loan, searched=str(loan_id), errors=[str(exc)], status_code=409)
    return RedirectResponse(f"/staff/collect?loan_id={loan_id}&done=1", status_code=303)
