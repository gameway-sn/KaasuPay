"""KYC actions: submit (customer), approve and reject (support).

The routers stay short; the rules live here.
  draft -> submitted -> approved | rejected,  and rejected -> submitted again.
"""
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import KycDocument, KycRecord, KycStatus, User
from app.schemas.kyc import KycForm
from app.services import verhoeff
from app.services.audit import record
from app.services.crypto import encrypt
from app.services.uploads import CheckedFile, delete_file, save_file


class KycStateError(Exception):
    """The action isn't allowed in the KYC's current state."""


def get_kyc(db: Session, user_id: int) -> KycRecord | None:
    return db.scalars(select(KycRecord).where(KycRecord.user_id == user_id)).first()


def can_submit(kyc: KycRecord | None) -> bool:
    return kyc is None or kyc.status in (KycStatus.DRAFT, KycStatus.REJECTED)


def submit_kyc(db: Session, user: User, form: KycForm, files: dict[str, CheckedFile]) -> KycRecord:
    """Save a checked KYC form and its files, and mark it submitted."""
    kyc = get_kyc(db, user.id)
    if not can_submit(kyc):
        raise KycStateError("KYC is already submitted or approved.")
    if kyc is None:
        kyc = KycRecord(user_id=user.id)
        db.add(kyc)

    # On a resubmission, the new files replace the old ones.
    old_files = [doc.stored_name for doc in kyc.documents]
    if old_files:
        kyc.documents.clear()
        db.flush()  # delete the old rows now, before adding new rows of the same kind

    saved = []
    try:
        for kind, checked in files.items():
            name = save_file(checked)
            saved.append(name)
            kyc.documents.append(KycDocument(
                kind=kind, stored_name=name,
                content_type=checked.content_type, size_bytes=len(checked.data),
            ))
        kyc.pan = form.pan
        kyc.aadhaar_encrypted = encrypt(form.aadhaar)
        kyc.aadhaar_last4 = form.aadhaar[-4:]
        kyc.status = KycStatus.SUBMITTED
        kyc.submitted_at = utcnow()
        kyc.rejection_reason = None
        kyc.reviewed_at = None
        kyc.reviewed_by_id = None
        db.flush()  # gives a new KYC its id for the audit line
        record(db, user, "kyc.submit", target_type="kyc", target_id=kyc.id, customer_id=user.id)
        db.commit()
    except Exception:
        # Database save failed: remove the files we just wrote, so nothing is left behind.
        db.rollback()
        for name in saved:
            delete_file(name)
        raise

    for name in old_files:
        delete_file(name)
    return kyc


def _review(db: Session, kyc: KycRecord, reviewer: User, status: KycStatus, reason: str | None) -> None:
    if kyc.status != KycStatus.SUBMITTED:
        raise KycStateError(f"This KYC is {kyc.status}, not waiting for review.")
    kyc.status = status
    kyc.rejection_reason = reason
    kyc.reviewed_at = utcnow()
    kyc.reviewed_by_id = reviewer.id
    record(db, reviewer, f"kyc.{status}", target_type="kyc", target_id=kyc.id,
           customer_id=kyc.user_id, detail=reason or "")
    db.commit()


def approve_kyc(db: Session, kyc: KycRecord, reviewer: User) -> None:
    _review(db, kyc, reviewer, KycStatus.APPROVED, None)


def reject_kyc(db: Session, kyc: KycRecord, reviewer: User, reason: str) -> None:
    _review(db, kyc, reviewer, KycStatus.REJECTED, reason)


def make_fake_aadhaar() -> str:
    """A random 12-digit number with a valid checksum, for demos. Not a real Aadhaar."""
    first = str(secrets.choice("23456789"))
    middle = "".join(str(secrets.randbelow(10)) for _ in range(10))
    number = first + middle + verhoeff.check_digit(first + middle)
    return f"{number[:4]} {number[4:8]} {number[8:]}"
