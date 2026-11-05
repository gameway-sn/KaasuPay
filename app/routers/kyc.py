"""KYC pages.

Customer:   GET/POST /kyc                       fill in and submit KYC
Support:    GET  /staff/kyc                     review queue
            GET  /staff/kyc/{id}                one KYC (Aadhaar masked)
            POST /staff/kyc/{id}/approve|reject
Documents:  GET  /kyc/documents/{id}            support: any; customer: own only; others: 403
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_role
from app.models import DOC_LABELS, DocKind, KycDocument, KycRecord, KycStatus, Role, User
from app.schemas.common import error_messages
from app.schemas.kyc import KycForm, RejectForm
from app.services.kyc import (
    KycStateError, approve_kyc, can_submit, get_kyc, make_fake_aadhaar, reject_kyc, submit_kyc,
)
from app.services.audit import record
from app.services.uploads import UploadError, check_upload, path_for
from app.templating import render

router = APIRouter()


# ======================= Customer side =======================

def _customer_page(request, user, kyc, form=None, errors=None, status_code=200):
    return render(request, "kyc/customer.html", {
        "user": user,
        "kyc": kyc,
        "can_submit": can_submit(kyc),
        "form": form or {},
        "errors": errors or [],
        "sample_aadhaar": make_fake_aadhaar(),
        "labels": DOC_LABELS,
    }, status_code=status_code)


@router.get("/kyc")
def kyc_page(
    request: Request,
    user: User = Depends(require_role(Role.CUSTOMER)),
    db: Session = Depends(get_db),
):
    return _customer_page(request, user, get_kyc(db, user.id))


@router.post("/kyc")
def kyc_submit(
    request: Request,
    pan: str = Form(""),
    aadhaar: str = Form(""),
    id_front: UploadFile | None = File(None),
    id_back: UploadFile | None = File(None),
    selfie: UploadFile | None = File(None),
    user: User = Depends(require_role(Role.CUSTOMER)),
    db: Session = Depends(get_db),
):
    kyc = get_kyc(db, user.id)
    if not can_submit(kyc):
        raise HTTPException(409, "Your KYC is already submitted or approved.")

    # Collect every problem at once, so the customer can fix them all in one go.
    errors = []
    form = None
    try:
        form = KycForm(pan=pan, aadhaar=aadhaar)
    except ValidationError as exc:
        errors += error_messages(exc)

    files = {}
    for kind, upload in ((DocKind.ID_FRONT, id_front), (DocKind.ID_BACK, id_back), (DocKind.SELFIE, selfie)):
        try:
            files[kind] = check_upload(upload, DOC_LABELS[kind])
        except UploadError as exc:
            errors.append(str(exc))

    if errors:
        # The customer may see their own full Aadhaar again while they are typing it.
        return _customer_page(request, user, kyc, {"pan": pan, "aadhaar": aadhaar}, errors, 422)

    submit_kyc(db, user, form, files)
    return RedirectResponse("/kyc", status_code=303)


# ======================= Support side =======================

@router.get("/staff/kyc")
def kyc_queue(
    request: Request,
    user: User = Depends(require_role(Role.SUPPORT)),
    db: Session = Depends(get_db),
):
    waiting = db.scalars(
        select(KycRecord).where(KycRecord.status == KycStatus.SUBMITTED).order_by(KycRecord.submitted_at)
    ).all()
    recent = db.scalars(
        select(KycRecord)
        .where(KycRecord.status.in_([KycStatus.APPROVED, KycStatus.REJECTED]))
        .order_by(KycRecord.reviewed_at.desc())
        .limit(10)
    ).all()
    return render(request, "staff/kyc_queue.html", {"user": user, "waiting": waiting, "recent": recent})


def _load_kyc(db: Session, kyc_id: int) -> KycRecord:
    kyc = db.get(KycRecord, kyc_id)
    if kyc is None:
        raise HTTPException(404, "No such KYC.")
    return kyc


def _review_page(request, user, kyc, errors=None, status_code=200):
    return render(request, "staff/kyc_review.html",
                  {"user": user, "kyc": kyc, "errors": errors or []}, status_code=status_code)


@router.get("/staff/kyc/{kyc_id}")
def kyc_review(
    request: Request,
    kyc_id: int,
    user: User = Depends(require_role(Role.SUPPORT)),
    db: Session = Depends(get_db),
):
    kyc = _load_kyc(db, kyc_id)
    # "Who viewed which customer's KYC" — logged every time the page is opened.
    record(db, user, "kyc.view", target_type="kyc", target_id=kyc.id, customer_id=kyc.user_id)
    db.commit()
    return _review_page(request, user, kyc)


@router.post("/staff/kyc/{kyc_id}/approve")
def kyc_approve(
    kyc_id: int,
    user: User = Depends(require_role(Role.SUPPORT)),
    db: Session = Depends(get_db),
):
    try:
        approve_kyc(db, _load_kyc(db, kyc_id), user)
    except KycStateError as exc:
        raise HTTPException(409, str(exc)) from None
    return RedirectResponse("/staff/kyc", status_code=303)


@router.post("/staff/kyc/{kyc_id}/reject")
def kyc_reject(
    request: Request,
    kyc_id: int,
    reason: str = Form(""),
    user: User = Depends(require_role(Role.SUPPORT)),
    db: Session = Depends(get_db),
):
    kyc = _load_kyc(db, kyc_id)
    try:
        form = RejectForm(reason=reason)
    except ValidationError as exc:
        return _review_page(request, user, kyc, error_messages(exc), 422)
    try:
        reject_kyc(db, kyc, user, form.reason)
    except KycStateError as exc:
        raise HTTPException(409, str(exc)) from None
    return RedirectResponse("/staff/kyc", status_code=303)


# ======================= Documents =======================

@router.get("/kyc/documents/{doc_id}")
def kyc_document(
    doc_id: int,
    user: User = Depends(require_role(Role.SUPPORT, Role.CUSTOMER)),  # everyone else: 403
    db: Session = Depends(get_db),
):
    doc = db.get(KycDocument, doc_id)
    # A customer asking for someone else's file gets 404, not 403:
    # we don't even admit that the file exists.
    if doc is None or (user.role == Role.CUSTOMER and doc.kyc.user_id != user.id):
        raise HTTPException(404, "No such document.")

    path = path_for(doc.stored_name)
    if not path.exists():
        raise HTTPException(404, "No such document.")

    record(db, user, "kyc.document_view", target_type="kyc", target_id=doc.kyc_id,
           customer_id=doc.kyc.user_id, detail=doc.label)
    db.commit()

    return FileResponse(path, media_type=doc.content_type, headers={
        "Content-Disposition": "inline",
        "Cache-Control": "no-store",            # don't keep ID photos in the browser cache
        "X-Content-Type-Options": "nosniff",    # browser must trust our content type, not guess
    })
