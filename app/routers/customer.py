"""Pages for logged-in customers."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import Role, User
from app.services.kyc import get_kyc
from app.services.loans import get_customer_loans, get_open_loan
from app.templating import render

router = APIRouter()


@router.get("/dashboard")
def dashboard(
    request: Request,
    user: User = Depends(require_role(Role.CUSTOMER)),
    db: Session = Depends(get_db),
):
    return render(request, "customer/dashboard.html", {
        "user": user,
        "kyc": get_kyc(db, user.id),
        "loans": get_customer_loans(db, user.id),
        "open_loan": get_open_loan(db, user.id),
    })
