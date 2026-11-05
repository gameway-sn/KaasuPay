"""Staff area. Every route here uses require_role(...), like a VLAN ACL."""
from fastapi import APIRouter, Depends, Request

from app.deps import require_role
from app.models import STAFF_ROLES, Role, User
from app.templating import render

router = APIRouter(prefix="/staff")

# Shown on the staff home page, straight from the roles table in CLAUDE.md.
ROLE_INFO = {
    Role.SUPPORT: {
        "vlan": "VLAN 20",
        "can": "Review KYC (masked Aadhaar), approve or reject it with a reason",
        "cannot": "Any money action",
    },
    Role.FINANCE: {
        "vlan": "VLAN 10",
        "can": "Approve disbursal, view the loan book and reports",
        "cannot": "Edit or approve KYC",
    },
    Role.IT_ADMIN: {
        "vlan": "VLAN 30",
        "can": "Manage staff accounts, read the audit log",
        "cannot": "Approve KYC or loans (separation of duties)",
    },
    Role.BRANCH_AGENT: {
        "vlan": "VLAN 110",
        "can": "Find a loan by its ID, record a cash EMI collection",
        "cannot": "View KYC documents or Aadhaar",
    },
}


@router.get("")
def staff_home(request: Request, user: User = Depends(require_role(*STAFF_ROLES))):
    return render(request, "staff/home.html", {"user": user, "info": ROLE_INFO[user.role]})
