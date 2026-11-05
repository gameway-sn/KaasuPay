"""IT admin: staff accounts and the audit log. IT admin only (VLAN 30).

GET  /staff/admin/staff                         list + "new staff" form
POST /staff/admin/staff                         create (temporary password shown once)
POST /staff/admin/staff/{id}/deactivate|activate|unlock|reset-password
GET  /staff/admin/audit?category=&customer_id=  read the audit log

Separation of duties: IT admins run accounts and read logs, but every KYC
and loan route still refuses them (403).
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import STAFF_ROLES, AuditEvent, Role, User
from app.schemas.admin import StaffCreateForm
from app.schemas.common import error_messages
from app.services import staff as staff_service
from app.services.audit import CATEGORIES, record
from app.templating import render

router = APIRouter(prefix="/staff/admin")

AUDIT_PAGE_SIZE = 200


# ======================= Staff accounts =======================

def _staff_page(request, user, db, *, form=None, errors=None, new_password=None, notice=None, status_code=200):
    return render(request, "admin/staff.html", {
        "user": user,
        "staff": staff_service.list_staff(db),
        "roles": STAFF_ROLES,
        "form": form or {},
        "errors": errors or [],
        "new_password": new_password,  # (staff member, password) shown once, never stored in plain text
        "notice": notice,
    }, status_code=status_code)


@router.get("/staff")
def staff_list(
    request: Request,
    user: User = Depends(require_role(Role.IT_ADMIN)),
    db: Session = Depends(get_db),
):
    return _staff_page(request, user, db)


@router.post("/staff")
def staff_create(
    request: Request,
    full_name: str = Form(""),
    phone: str = Form(""),
    role: str = Form(""),
    user: User = Depends(require_role(Role.IT_ADMIN)),
    db: Session = Depends(get_db),
):
    typed = {"full_name": full_name, "phone": phone, "role": role}
    try:
        form = StaffCreateForm(**typed)
    except ValidationError as exc:
        return _staff_page(request, user, db, form=typed, errors=error_messages(exc), status_code=422)
    try:
        staff, password = staff_service.create_staff(db, user, form)
    except staff_service.StaffAdminError as exc:
        return _staff_page(request, user, db, form=typed, errors=[str(exc)], status_code=409)
    return _staff_page(request, user, db, new_password=(staff, password))


def _load(db: Session, staff_id: int) -> User:
    staff = staff_service.get_staff(db, staff_id)
    if staff is None:
        raise HTTPException(404, "No such staff account.")  # customers can't be managed here
    return staff


@router.post("/staff/{staff_id}/{action}")
def staff_action(
    request: Request,
    staff_id: int,
    action: str,
    user: User = Depends(require_role(Role.IT_ADMIN)),
    db: Session = Depends(get_db),
):
    staff = _load(db, staff_id)
    try:
        if action == "deactivate":
            staff_service.set_active(db, user, staff, False)
        elif action == "activate":
            staff_service.set_active(db, user, staff, True)
        elif action == "unlock":
            staff_service.unlock(db, user, staff)
        elif action == "reset-password":
            password = staff_service.reset_password(db, user, staff)
            return _staff_page(request, user, db, new_password=(staff, password))
        else:
            raise HTTPException(404, "Unknown action.")
    except staff_service.StaffAdminError as exc:
        return _staff_page(request, user, db, errors=[str(exc)], status_code=409)
    return RedirectResponse("/staff/admin/staff", status_code=303)


# ======================= Audit log =======================

@router.get("/audit")
def audit_log(
    request: Request,
    category: str = "",
    customer_id: str = "",
    user: User = Depends(require_role(Role.IT_ADMIN)),
    db: Session = Depends(get_db),
):
    query = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(AUDIT_PAGE_SIZE)
    if category in CATEGORIES.values():
        query = query.where(AuditEvent.action.startswith(category))
    customer = None
    if customer_id.strip().isascii() and customer_id.strip().isdigit():
        customer = db.get(User, int(customer_id))
        query = query.where(AuditEvent.customer_id == int(customer_id))

    events = db.scalars(query).all()

    # Watching the watchers: reading the log is itself logged.
    record(db, user, "admin.audit_view", detail=f"category={category or 'all'} customer={customer_id or 'any'}")
    db.commit()

    customers = db.scalars(select(User).where(User.role == Role.CUSTOMER).order_by(User.full_name)).all()
    return render(request, "admin/audit.html", {
        "user": user,
        "events": events,
        "categories": CATEGORIES,
        "category": category,
        "customers": customers,
        "customer_id": customer_id,
        "customer": customer,
        "page_size": AUDIT_PAGE_SIZE,
    })
