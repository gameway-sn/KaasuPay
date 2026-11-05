"""Pages for logged-in customers."""
from fastapi import APIRouter, Depends, Request

from app.deps import require_role
from app.models import Role, User
from app.templating import render

router = APIRouter()


@router.get("/dashboard")
def dashboard(request: Request, user: User = Depends(require_role(Role.CUSTOMER))):
    return render(request, "customer/dashboard.html", {"user": user})
